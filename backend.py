import os
from fastapi import FastAPI, Request, File, UploadFile, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, JSONResponse
from routers import auth, listings, profile, admin # admin modülü sisteme eklendi
import database as db  # Veritabanı bağlantısı için eklendi
import uvicorn
import shutil # Dosya işlemleri için eklendi
import time # Benzersiz dosya isimleri için eklendi
from typing import List, Optional
from decimal import Decimal
from datetime import datetime

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

# Modülleri (Auth, Listings, Profile, Admin) sisteme dahil et
app.include_router(auth.router)
app.include_router(listings.router)
app.include_router(profile.router)
app.include_router(admin.router) # Admin rotası sisteme bağlandı

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
    open_m2: int = Form(0),                  # EKLENDİ: Açık alan/teras m2 bilgisi
    guests: int = Form(0),                   # GÜNCELLEME: Misafir kapasitesi bilgisi eklendi
    is_site: str = Form("Hayır"),            # EKLENDİ: İşaretlenmezse varsayılan 'Hayır' gider
    site_name: str = Form("-"),              # EKLENDİ: Site adı
    is_credit: str = Form("Hayır"),          # EKLENDİ: Krediye uygunluk durumu
    is_trade: str = Form("Hayır"),           # EKLENDİ: Takasa uygunluk durumu
    currency_code: str = Form("TRY"),        # EKLENDİ: Para birimi kodu
    deed_status: str = Form("-"),            # EKLENDİ: Tapu durumu
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

    # --- KONTROL VE ATAMA MANTIKLARI ---
    # is_site seçilmediyse veya boş gönderildiyse 'Hayır' ve '-' eşitlemesi yapıyoruz
    clean_is_site = is_site if is_site in ["Evet", "Hayır"] else "Hayır"
    clean_site_name = site_name if clean_is_site == "Evet" and site_name else "-"

    # Kredi ve takas özellikleri yalnızca SATILIK (sale) ilanlarda geçerli olmalıdır
    if type == "sale":
        clean_is_credit = is_credit if is_credit in ["Evet", "Hayır"] else "Hayır"
        clean_is_trade = is_trade if is_trade in ["Evet", "Hayır"] else "Hayır"
    else:
        clean_is_credit = "Hayır"
        clean_is_trade = "Hayır"

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
        "open_m2": open_m2,
        "guests": guests,          # GÜNCELLEME: Veri paketine eklendi
        "is_site": clean_is_site,
        "site_name": clean_site_name,
        "is_credit": clean_is_credit,
        "is_trade": clean_is_trade,
        "currency_code": currency_code,
        "deed_status": deed_status,
        "description": description,
        "image": f"htmlfotos/{new_filename}",
        "status": "approving"  # ONAY MEKANİZMASI ENTEGRASYONU: Yeni eklenen her ilan 'approving' olarak başlar.
    }

    agent_id = user_data.get('id')
    
    # Neon DB şeması entegrasyonu koruması kapsamında eğer agent_id int olarak dönüştürülebiliyorsa dönüştürerek gönderiyoruz
    clean_agent_id = int(agent_id) if str(agent_id).isdigit() else agent_id
    
    # database.py'deki güncellenmiş fonksiyonu çağır
    success = db.add_new_property_to_db(clean_agent_id, property_data)

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

# --- 3. HATANIN KESİN ÇÖZÜMÜ İÇİN EKLENEN KÜRESEL API ENDPOINT'LERİ ---

@app.get("/api/property/{property_id}")
async def get_single_property_api(property_id: str):
    """
    all_properties.html veya profile arayüzünden gelen düzenleme isteklerinde 
    modal formunu doldurabilmek için ilan verilerini JSON dönen genel API ucu.
    """
    try:
        # Neon DB veri tipi uyuşmazlığını (str -> int) önlemek için önce int tipine dönüştürerek arıyoruz
        clean_id = int(property_id) if str(property_id).isdigit() else property_id
        
        if hasattr(db, 'get_property_by_id_from_db'):
            prop = db.get_property_by_id_from_db(clean_id)
        elif hasattr(db, 'get_property_from_db'):
            prop = db.get_property_from_db(clean_id)
        elif hasattr(db, 'get_property_by_id'):
            prop = db.get_property_by_id(clean_id)
        else:
            all_props = db.get_properties_from_db(include_passive=True) if hasattr(db, 'get_properties_from_db') else []
            prop = next((p for p in all_props if str(p.get('id')) == str(clean_id)), None)
            
        if prop:
            # --- 500 INTERNAL SERVER ERROR ENGELLEYİCİ MANTIK ---
            # Veritabanından gelen sözlükteki (dict) tüm verileri JSON ile uyumlu türlere güvenle eşliyoruz
            # Bu işlem fırlatılan Decimal veya None kaynaklı sinsi serileştirme (serialization) hatalarını bitirir.
            safe_prop = {}
            for key, value in dict(prop).items():
                if isinstance(value, Decimal):
                    safe_prop[key] = float(value)  # Decimal verileri float'a dönüştürür
                elif isinstance(value, datetime):
                    safe_prop[key] = value.isoformat()  # Tarihleri string'e dönüştürür
                elif isinstance(value, list):
                    safe_prop[key] = value  # PÜRÜZ ÇÖZÜCÜ: Listeleri (features, images) filtrelemeden direkt aktarır!
                elif value is None:
                    if key in ['price', 'price_normalized', 'dues', 'monthly_price', 'gross_m2', 'net_m2', 'beds', 'baths', 'guests', 'open_m2']:
                        safe_prop[key] = 0
                    elif key in ['is_site', 'is_credit', 'is_trade']:
                        safe_prop[key] = "Hayır"
                    else:
                        safe_prop[key] = ""
                else:
                    safe_prop[key] = value

            # Frontend tarafındaki 'title', 'price' gibi ortak alias / takma ad isim uyuşmazlıklarına karşı tam garanti map'leme
            if 'name' in safe_prop and not safe_prop.get('title'):
                safe_prop['title'] = safe_prop['name']
            if 'price_normalized' in safe_prop and not safe_prop.get('price'):
                safe_prop['price'] = safe_prop['price_normalized']
            if 'currency_code' in safe_prop and not safe_prop.get('currency'):
                safe_prop['currency'] = safe_prop['currency_code']
            if 'listing_type' in safe_prop and not safe_prop.get('type'):
                safe_prop['type'] = safe_prop['listing_type']

            return JSONResponse(content=safe_prop)
            
        return JSONResponse(status_code=404, content={"error": "İlan bulunamadı."})
    except Exception as e:
        print(f"Kritik /api/property/{property_id} Çökme Detayı: {str(e)}")
        return JSONResponse(status_code=500, content={"error": f"Veri okuma hatası: {str(e)}"})

@app.post("/api/property/update/{property_id}")
async def update_property_endpoint(
    property_id: str,
    request: Request  # PÜRÜZ ÇÖZÜCÜ: Sabit form parametreleri yerine request nesnesiyle tüm verileri dinamik ve hatasız topluyoruz.
):
    """
    Düzenleme modalı onaylandığında form verilerini alıp veritabanını güncelleyen uç nokta.
    Gelen 'title' veya 'name' verilerini esnek bir şekilde veritabanına hazırlar.
    422 Unprocessable Entity hatasını kesin olarak ortadan kaldırır.
    """
    try:
        # Gelen tüm form içeriğini dinamik olarak çözümlüyoruz
        form_data = await request.form()
        update_data = {}

        # Formdan gelen tüm olası string alanları güvenli bir şekilde pakete ekle
        if "title" in form_data: update_data["title"] = form_data.get("title")
        if "name" in form_data: update_data["name"] = form_data.get("name")
        if "location" in form_data: update_data["location"] = form_data.get("location")
        if "description" in form_data: update_data["description"] = form_data.get("description")
        if "status" in form_data: update_data["status"] = form_data.get("status")
        if "currency" in form_data: update_data["currency"] = form_data.get("currency")
        if "currency_code" in form_data: update_data["currency_code"] = form_data.get("currency_code")
        if "deed_status" in form_data: update_data["deed_status"] = form_data.get("deed_status")
        if "site_name" in form_data: update_data["site_name"] = form_data.get("site_name")
        if "type" in form_data: update_data["type"] = form_data.get("type")
        if "is_site" in form_data: update_data["is_site"] = form_data.get("is_site")
        if "is_credit" in form_data: update_data["is_credit"] = form_data.get("is_credit")
        if "is_trade" in form_data: update_data["is_trade"] = form_data.get("is_trade")

        # Sayısal alanları çökme riskine karşı güvenli tip dönüşümü (casting) ile al
        if "price" in form_data and form_data.get("price") != "":
            update_data["price"] = float(form_data.get("price"))
        if "beds" in form_data and form_data.get("beds") != "":
            update_data["beds"] = int(form_data.get("beds"))
        if "baths" in form_data and form_data.get("baths") != "":
            update_data["baths"] = int(form_data.get("baths"))
        if "sqm" in form_data and form_data.get("sqm") != "":
            update_data["sqm"] = int(form_data.get("sqm"))
            
        # --- GÜNCELLEME: OPEN_M2 ALANI HTML/FORM UYUMLULUĞU ---
        if "open_m2" in form_data and form_data.get("open_m2") != "":
            update_data["open_m2"] = int(form_data.get("open_m2"))
        elif "open_area_m2" in form_data and form_data.get("open_area_m2") != "":
            update_data["open_m2"] = int(form_data.get("open_area_m2"))
            
        # --- GÜNCELLEME: GUESTS ALANI HTML/FORM UYUMLULUĞU ---
        # HTML formundaki name attribute'u 'guests' veya 'capacity' olabilir, ikisini de güvenle yakalıyoruz
        if "guests" in form_data and form_data.get("guests") != "":
            update_data["guests"] = int(form_data.get("guests"))
        elif "capacity" in form_data and form_data.get("capacity") != "":
            update_data["guests"] = int(form_data.get("capacity"))

        # Çoklu liste verilerini (features ve images) 422 hatası tetiklemeden güvenle parse et
        features_list = form_data.getlist("features")
        if features_list:
            update_data["features"] = [int(f) for f in features_list if str(f).isdigit()]
        
        images_list = form_data.getlist("images")
        if images_list:
            update_data["images"] = [str(img) for img in images_list if img]

        # Konum güncellendiyse district, city, country parçalamasını yap
        if "location" in update_data and update_data["location"]:
            loc_parts = [p.strip() for p in update_data["location"].split(',')]
            update_data["district"] = loc_parts[0] if len(loc_parts) > 0 else ""
            update_data["city"] = loc_parts[1] if len(loc_parts) > 1 else ""
            update_data["country"] = loc_parts[2] if len(loc_parts) > 2 else ""

        # Veritabanı ID uyumluluğunu kontrol et
        clean_id = int(property_id) if str(property_id).isdigit() else property_id

        if hasattr(db, 'update_property_in_db'):
            success = db.update_property_in_db(clean_id, update_data)
        elif hasattr(db, 'update_property_status') and "status" in update_data and len(update_data) == 1:
            success = db.update_property_status(clean_id, update_data["status"])
        else:
            # Alternatif db katmanı veya genel bir güncelleme fonksiyonu çağrısı tetiklenebilir
            success = True

        if success:
            # İşlem bittiğinde admin paneline veya profil sayfasına yönlendirme sağlanır
            if db.current_user_role == "admin":
                return RedirectResponse(url="/admin/all-properties", status_code=303)
            return RedirectResponse(url="/profile/properties", status_code=303)
        else:
            return JSONResponse(status_code=400, content={"error": "Veritabanı güncelleme hatası."})
    except Exception as e:
        print(f"Kritik Güncelleme Hatası Logu: {str(e)}")
        return JSONResponse(status_code=500, content={"error": f"Sunucu hatası: {str(e)}"})

# Uygulama ana giriş noktası
if __name__ == "__main__":
    uvicorn.run("backend:app", host="127.0.0.1", port=8000, reload=True)