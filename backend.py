import os
from fastapi import FastAPI, Request, File, UploadFile, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from routers import auth, listings, profile
import database as db  # Veritabanı bağlantısı için eklendi
import uvicorn

app = FastAPI()

# Projenin ana dizinini belirle
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Şablon ve Statik dosya yollarını bağla
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# ÖNEMLİ: Statik dosyaları dışarı açan kısım. 
# Bu satır sayesinde 'static' klasörü içindeki her şeye (htmlfotos dahil) erişebilirsin.
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

# Modülleri (Auth, Listings, Profile) sisteme dahil et
# Not: listings.router artık içeride 'property' isimlendirmelerini kullanıyor.
app.include_router(auth.router)
app.include_router(listings.router)
app.include_router(profile.router)

# --- GLOBAL TEMPLATE CONTEXT ---
# Bu ayar, her render işleminde 'db.current_user_role' gibi değişkenlerin 
# template'lere otomatik gitmesini sağlar (Hata riskini azaltır).
templates.env.globals.update(
    current_user_role=lambda: db.current_user_role,
    current_user_data=lambda: db.current_user_data
)

@app.middleware("http")
async def db_session_middleware(request: Request, call_next):
    """
    Bu middleware, her sayfa isteğinde veritabanı durumunu 
    ve oturum bilgilerini kontrol eder.
    """
    # İsteği işlemeden önce yapılacaklar buraya eklenebilir
    response = await call_next(request)
    
    # İstek bittikten sonra yapılacaklar (Loglama vb.)
    return response

# Ana sayfa yönlendirmesi (Eğer / direkt home'a gitsin istersen)
@app.get("/")
async def root(request: Request):
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/home")

# --- DESKTOP1 GÜNCELLEMESİ İÇİN HAZIRLIK ---
# Çoklu fotoğraf ve dinamik özellikler için gerekli olan
# tüm router bağlantıları yukarıdaki app.include_router hatlarında aktif.

# Uygulama ana giriş noktası
if __name__ == "__main__":
    # Dosya adın 'backend.py' olduğu için "backend:app" olarak ayarlandı.
    # reload=True: Geliştirme aşamasında kod değiştikçe otomatik yeniler.
    
    # 127.0.0.1 yerine 0.0.0.0 kullanmak dış erişimler için daha sağlıklıdır 
    # ama yerel test için 127.0.0.1 (localhost) kalabilir.
    uvicorn.run("backend:app", host="127.0.0.1", port=8000, reload=True)