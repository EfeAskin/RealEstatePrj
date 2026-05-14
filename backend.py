import os
from fastapi import FastAPI, Request, File, UploadFile, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, JSONResponse
from routers import auth, listings, profile
import database as db  # Veritabanı bağlantısı için eklendi
import uvicorn
import shutil # Dosya işlemleri için eklendi
import time # Benzersiz dosya isimleri için eklendi
from typing import List

app = FastAPI()

# Projenin ana dizinini belirle
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Şablon ve Statik dosya yollarını bağla
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# --- STATİK DOSYA AYARLARI ---
# 1. Genel statik klasörünü bağla (/static/htmlfotos/... şeklinde erişim için)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

# 2. Resimlerin doğrudan bulunabilmesi için (404 hatasını çözen kritik ekleme)
# Bu satır, tarayıcı direkt /htmlfotos/villa.png dediğinde static içindeki o klasöre bakar.
app.mount("/htmlfotos", StaticFiles(directory=os.path.join(BASE_DIR, "static/htmlfotos")), name="htmlfotos_direct")

# Modülleri (Auth, Listings, Profile) sisteme dahil et
app.include_router(auth.router)
app.include_router(listings.router)
app.include_router(profile.router)

# --- GLOBAL TEMPLATE CONTEXT ---
# Bu ayar, her render işleminde 'db.current_user_role' gibi değişkenlerin 
# template'lere otomatik gitmesini sağlar.
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
    response = await call_next(request)
    return response

# Ana sayfa yönlendirmesi
@app.get("/")
async def root(request: Request):
    return RedirectResponse(url="/home")

# --- YENİ İLAN EKLEME ENDPOINT (Pop-up Formu İçin) ---
@app.post("/add-property")
async def add_property(
    request: Request,
    name: str = Form(...),
    location: str = Form(...),
    price: float = Form(...),
    type: str = Form(...), # HTML formundan 'type' olarak geliyor (rent/sale)
    beds: int = Form(0),
    baths: int = Form(0),
    sqm: int = Form(0),
    description: str = Form(None),
    main_image: UploadFile = File(...)
):
    """
    Basit pop-up formdan gelen verileri kaydeder. 
    Kolon isimleri Neon DB (listing_type) ile tam uyumlu hale getirilmiştir.
    """
    
    # Kullanıcı ID'sini al ve Yetki Kontrolü Yap
    user_data = getattr(db, 'current_user_data', None)
    if not user_data or db.current_user_role != 'agent':
        return JSONResponse(status_code=401, content={"error": "İlan vermek için Agent hesabı ile giriş yapmalısınız."})

    # 1. Dosyayı Kaydet
    upload_folder = os.path.join(BASE_DIR, "static/htmlfotos") 
    if not os.path.exists(upload_folder):
        os.makedirs(upload_folder)

    # Dosya adını benzersiz yap
    file_extension = os.path.splitext(main_image.filename)[1]
    new_filename = f"prop_{int(time.time())}{file_extension}"
    file_path = os.path.join(upload_folder, new_filename)

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(main_image.file, buffer)
    except Exception as e:
        print(f"Dosya kaydetme hatası: {e}")
        return JSONResponse(status_code=500, content={"error": "Dosya yüklenemedi."})

    # --- KONUM PARÇALAMA MANTIĞI ---
    loc_parts = [p.strip() for p in location.split(',')]
    district = loc_parts[0] if len(loc_parts) > 0 else ""
    city = loc_parts[1] if len(loc_parts) > 1 else ""
    country = loc_parts[2] if len(loc_parts) > 2 else ""

    # 2. Veritabanına Yazılacak Veri Paketi
    # database.py içindeki add_new_property_to_db fonksiyonunun beklediği key'ler ile eşitledik
    property_data = {
        "name": name,
        "location": location,      
        "district": district,      
        "city": city,              
        "country": country,        
        "price": price,            
        "type": type,              # db fonksiyonunda data.get('type') kullanılıyor
        "beds": beds,
        "baths": baths,
        "sqm": sqm,
        "description": description,
        "image": f"htmlfotos/{new_filename}" 
    }

    agent_id = user_data.get('id')
    
    # database.py'deki güncellenmiş fonksiyonu çağır
    success = db.add_new_property_to_db(agent_id, property_data)

    if success:
        return RedirectResponse(url="/profile/properties", status_code=303)
    else:
        # Hata durumunda yüklenen resmi silebiliriz (opsiyonel)
        if os.path.exists(file_path):
            os.remove(file_path)
        return JSONResponse(status_code=500, content={"error": "Veritabanı kaydı sırasında bir hata oluştu. Agent tablosunda kaydınızın olduğundan emin olun."})

# --- ÖZELLİKLERİ ÇEKEN API ---
@app.get("/api/features")
async def get_features():
    """
    Neon PostgreSQL üzerindeki 'features' tablosundan tüm özellikleri çeker.
    """
    try:
        features = db.get_all_features_from_db()
        return features
    except Exception as e:
        print(f"API Hatası (Features): {e}")
        return []

# Uygulama ana giriş noktası
if __name__ == "__main__":
    uvicorn.run("backend:app", host="127.0.0.1", port=8000, reload=True)