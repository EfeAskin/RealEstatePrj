import os
import time as _time
import pytz
import database as db
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.gzip import GZipMiddleware

# Router Modüllerini İçeri Aktar
from routers import admin, auth, chat, listings, profile
from routers import pages, messages, properties
from routers import property_filter
from routers import favorites  # Dosyanın klasör yoluna göre import et # Yeni ayrılan modüller
from routers import ai_search  # AI semantic search + recommendations (JSON endpoints)
from routers import aichat  # Conversational property-search assistant (AI Chat page)
from routers import tickets

app = FastAPI()

# Yanıtları sıkıştır (daha küçük HTML/JSON -> daha hızlı yükleme)
app.add_middleware(GZipMiddleware, minimum_size=500)

# --- PERFORMANS: middleware sorgularını kısa süreli önbellekle ---
# Her istekte kullanıcı + okunmamış mesaj sorgusu yapmak yerine, kısa TTL'li
# süreç-içi önbellek kullanılır. Statik dosya istekleri DB'ye hiç dokunmaz.
_user_cache = {}      # user_id_cookie -> (user, expiry)
_unread_cache = {}    # user_id -> (count, expiry)
_USER_TTL = 10.0
_UNREAD_TTL = 20.0
_STATIC_PREFIXES = ("/static", "/htmlfotos", "/favicon")

# Projenin ana dizinini belirle
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Şablon ve Statik dosya yollarını bağla
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Zaman dilimi tanımlamaları
tr_tz = pytz.timezone("Europe/Istanbul")

# --- STATİK DOSYA AYARLARI ---
# Imported listing images can be absolute http(s) URLs; if a template ever feeds one
# into /static/... (e.g. a stale cached page), os.stat on Windows raises OSError [WinError 123]
# for the ':' in 'https:' -> unhandled 500 + ugly traceback. Treat such paths as a clean 404.
class SafeStaticFiles(StaticFiles):
    def lookup_path(self, path):
        try:
            return super().lookup_path(path)
        except (OSError, ValueError):
            return "", None

app.mount("/static", SafeStaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
app.mount("/htmlfotos", SafeStaticFiles(directory=os.path.join(BASE_DIR, "static/htmlfotos")), name="htmlfotos_direct")

# Tarayıcılar her sekmede otomatik /favicon.ico ister; rota yoksa log 404'le dolar.
_FAVICON_PATH = os.path.join(BASE_DIR, "static/htmlfotos/favicon.png")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    from fastapi.responses import FileResponse
    return FileResponse(_FAVICON_PATH)

# --- JINJA2 SİHİRLİ ŞABLONLARI İÇİN AKILLI ESNEK SINIFLAR ---
class CallableDict(dict):
    def __call__(self, *args, **kwargs):
        return self
    def __getattr__(self, item):
        return self.get(item, "")

class CallableStr(str):
    def __call__(self, *args, **kwargs):
        return self

# Şablon Nesnelerini Küresel Jinja Ortamına Paylaştır (Router'lar erişebilsin diye)
templates.env.globals["CallableDict"] = CallableDict
templates.env.globals["CallableStr"] = CallableStr

# --- DİNAMİK OTURUM VE TEMPLATE BAĞLANTISI (MIDDLEWARE) ---
@app.middleware("http")
async def db_session_middleware(request: Request, call_next):
    # Statik/asset istekleri DB'ye hiç dokunmasın — her sayfa onlarca asset yükler.
    if request.url.path.startswith(_STATIC_PREFIXES):
        return await call_next(request)

    now = _time.time()
    user_id_cookie = request.cookies.get("user_id")
    current_user = None
    unread_count = 0

    if user_id_cookie:
        cached = _user_cache.get(user_id_cookie)
        if cached and cached[1] > now:
            current_user = cached[0]
        else:
            try:
                current_user = db.get_user_from_cookie(user_id_cookie)
            except Exception as e:
                print(f"Middleware Kullanıcı Çerez Okuma Hatası: {e}")
                current_user = None
            _user_cache[user_id_cookie] = (current_user, now + _USER_TTL)

    # Request-scoped user: lets routes (e.g. admin) reuse the cached user resolved
    # here instead of re-querying the DB per page. Concurrency-safe, unlike the globals.
    request.state.user = current_user

    if current_user:
        safe_user_data = CallableDict(current_user)
        safe_user_role = CallableStr(current_user.get("role", "guest"))

        templates.env.globals["current_user_role"] = safe_user_role
        templates.env.globals["current_user_data"] = safe_user_data

        db.current_user_role = current_user.get("role", "guest")
        db.current_user_data = current_user
        db.current_user_email = current_user.get("email")

        # --- OKUNMAMIŞ MESAJ SAYISI (kısa TTL ile önbellekli) ---
        current_user_id = current_user.get("id")
        if current_user_id:
            cu = _unread_cache.get(current_user_id)
            if cu and cu[1] > now:
                unread_count = cu[0]
            else:
                conn = db.get_db_connection()
                if conn:
                    try:
                        cur = conn.cursor()
                        cur.execute(
                            """
                            SELECT COUNT(*) FROM chat_messages m
                            JOIN chat_rooms r ON m.room_id = r.id
                            WHERE (r.user_id = %s OR r.agent_id = %s)
                            AND m.sender_id != %s
                            AND m.is_read = FALSE
                            AND r.is_ai_chat = FALSE
                            """,
                            (int(current_user_id), int(current_user_id), int(current_user_id))
                        )
                        row = cur.fetchone()
                        unread_count = row[0] if row else 0
                        cur.close()
                    except Exception as e:
                        print(f"Middleware Okunmamış Mesaj Sayma Hatası: {e}")
                    finally:
                        conn.close()
                _unread_cache[current_user_id] = (unread_count, now + _UNREAD_TTL)
    else:
        empty_user_data = CallableDict({})
        guest_role = CallableStr("guest")

        templates.env.globals["current_user_role"] = guest_role
        templates.env.globals["current_user_data"] = empty_user_data

        db.current_user_role = "guest"
        db.current_user_data = {}
        db.current_user_email = None

    templates.env.globals["unread_messages_count"] = unread_count

    response = await call_next(request)
    return response

# --- MEVCUT VE YENİ ROUTER KAYITLARI ---
app.include_router(auth.router)
app.include_router(listings.router)
app.include_router(profile.router)
app.include_router(admin.router)
app.include_router(chat.router)

# Yeni oluşturulan router modüllerinin sisteme bağlanması
app.include_router(pages.router)
app.include_router(messages.router)
app.include_router(properties.router)
app.include_router(property_filter.router)
app.include_router(favorites.router)  # Yeni favoriler router'ını ekle
app.include_router(ai_search.router)  # AI semantic search + recommendation endpoints
app.include_router(aichat.router)  # Conversational AI Chat assistant (/aichat + /api/ai-chat)
app.include_router(tickets.router)  # Destek bileti sistemi için router

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend:app", host="127.0.0.1", port=8000, reload=True)