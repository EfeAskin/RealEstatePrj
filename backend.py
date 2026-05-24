import os
import pytz
import database as db
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Router Modüllerini İçeri Aktar
from routers import admin, auth, chat, listings, profile
from routers import pages, messages, properties
from routers import property_filter
from routers import favorites  # Dosyanın klasör yoluna göre import et # Yeni ayrılan modüller

app = FastAPI()

# Projenin ana dizinini belirle
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Şablon ve Statik dosya yollarını bağla
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Zaman dilimi tanımlamaları
tr_tz = pytz.timezone("Europe/Istanbul")

# --- STATİK DOSYA AYARLARI ---
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
app.mount("/htmlfotos", StaticFiles(directory=os.path.join(BASE_DIR, "static/htmlfotos")), name="htmlfotos_direct")

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
    user_id_cookie = request.cookies.get("user_id")
    current_user = None
    unread_count = 0
    
    if user_id_cookie:
        try:
            current_user = db.get_user_from_cookie(user_id_cookie)
        except Exception as e:
            print(f"Middleware Kullanıcı Çerez Okuma Hatası: {e}")
            current_user = None
    
    if current_user:
        safe_user_data = CallableDict(current_user)
        safe_user_role = CallableStr(current_user.get("role", "guest"))
        
        templates.env.globals["current_user_role"] = safe_user_role
        templates.env.globals["current_user_data"] = safe_user_data
        
        db.current_user_role = current_user.get("role", "guest")
        db.current_user_data = current_user
        db.current_user_email = current_user.get("email")
        
        # --- KÜRESEL OKUNMAMIŞ MESAJ SAYMA MOTORU ---
        current_user_id = current_user.get("id")
        if current_user_id:
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend:app", host="127.0.0.1", port=8000, reload=True)