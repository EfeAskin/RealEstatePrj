from fastapi import APIRouter, Request, Query, File, UploadFile, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import database as db
import math
import os
import uuid
from typing import List

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# Fotoğrafların kaydedileceği klasör
UPLOAD_DIR = "static/htmlfotos"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

# --- YARDIMCI FONKSİYONLAR ---

def format_currency(value):
    """Sayıyı binlik ayracı (nokta) ile formatlar."""
    try:
        if value is None or value == "" or value == "None":
            return "0"
        num = float(value)
        if num == 0:
            return "0"
        return "{:,.0f}".format(num).replace(",", ".")
    except (ValueError, TypeError):
        return str(value)

def get_currency_symbol(code):
    """Döviz koduna göre sembol döner."""
    symbols = {'TRY': '₺', 'USD': '$', 'EUR': '€', 'GBP': '£'}
    return symbols.get(str(code).upper(), '₺')

def process_property_data(property_item):
    """Neon DB kolon isimlerine göre tam eşleme ve RESİM YOLU KONTROLÜ."""
    if not property_item:
        return None
    
    # --- RESİM YOLU DÜZELTME GÜNCELLEMESİ (ÇİFTLEME HATASI ÇÖZÜMÜ) ---
    raw_image = property_item.get("image")
    if raw_image:
        # Terminaldeki 404 hatasını çözmek için: 
        # Veritabanındaki yolu (htmlfotos/...) olduğu gibi bırakıyoruz.
        # HTML tarafında src="/static/{{ property.image }}" kullanıldığı için yollar birleşecektir.
        property_item["image"] = str(raw_image).strip()
    else:
        property_item["image"] = "htmlfotos/default.jpg"
    
    # "type" kolonu hatasını burada "listing_type" önceliğiyle çözüyoruz
    raw_type = property_item.get("listing_type") or property_item.get("type", "rent")
    p_type = str(raw_type).lower()
    
    if p_type in ["sale", "satılık"]:
        append_type = "FOR SALE"
        property_item["is_sale"] = True
    else:
        append_type = "FOR RENT"
        property_item["is_sale"] = False
        
    property_item["display_type"] = append_type
        
    # Neon DB'deki yeni kolon ismine göre kontrol
    raw_price = property_item.get("price_normalized")
    if raw_price is None or str(raw_price) == "0" or raw_price == "":
        raw_price = property_item.get("price", 0)

    try:
        price_float = float(raw_price) if raw_price else 0
        property_item["formatted_price"] = format_currency(price_float)
    except:
        property_item["formatted_price"] = "0"
    
    curr_code = property_item.get("currency_code") or property_item.get("currency", "TRY")
    property_item["currency_symbol"] = get_currency_symbol(curr_code)

    # UI tarafındaki değişkenleri DB kolonlarıyla eşleştirme (Arayüz Uyumu Güvencesi)
    if 'name' in property_item and not property_item.get('title'):
        property_item['title'] = property_item['name']
    if 'price_normalized' in property_item and not property_item.get('price'):
        property_item['price'] = property_item['price_normalized']

    # --- KÖKLÜ VERİ DEĞİŞİM DÜZELTMESİ ---
    property_item["net_m2"] = property_item.get("net_m2") or 0
    property_item["room_count"] = property_item.get("room_count") or "3+2"
    property_item["beds"] = property_item.get("beds") or 0
    
    # Baths kolonu db'de bath_count olarak geçebilir
    property_item["baths"] = property_item.get("bath_count") or property_item.get("baths") or 0

    if "dues" in property_item and property_item["dues"] not in [None, "N/A"]:
        property_item["formatted_dues"] = format_currency(property_item["dues"])
    
    if "property_type" in property_item and property_item["property_type"]:
        property_type_val = property_item.get("property_type")
        property_type_str = str(property_type_val).strip()
        property_item["property_type"] = property_type_str.capitalize() if property_type_str else "N/A"
    
    return property_item

templates.env.filters["currency"] = format_currency

# --- ÖZELLİKLERİ GETİREN API ---
@router.get("/api/features")
async def get_features():
    """Frontend'deki checkbox'lar için veritabanındaki tüm özellikleri döner."""
    features = db.get_all_features_from_db()
    return features

# --- GELİŞMİŞ İLAN EKLEME ENDPOINT'İ ---
@router.post("/add-property-full")
async def add_property_full(
    request: Request,
    title: str = Form(...),
    location: str = Form(...),
    price: float = Form(...),
    currency_code: str = Form("TRY"),
    listing_type: str = Form("rent"), # 'type' yerine 'listing_type' kullanıyoruz
    property_type: str = Form(None),
    room_count: str = Form(None),
    gross_m2: int = Form(0),
    net_m2: int = Form(0),
    building_age: str = Form(None),
    heating: str = Form(None),
    deed_status: str = Form(None),
    dues: float = Form(0),
    description: str = Form(""),
    features: List[str] = Form([]),
    images: List[UploadFile] = File(...)
):
    # Agent kontrolü
    user_obj = getattr(db, 'current_user_data', None)
    if not user_obj or db.current_user_role != 'agent':
        return JSONResponse(status_code=403, content={"error": "Sadece emlakçılar ilan verebilir."})

    agent_id = user_obj.get("id")
    image_urls = []
    main_image_url = "" # Kapak fotoğrafı için değişken

    # 1. Resimleri Klasöre Kaydet
    for index, img in enumerate(images):
        if img.filename:
            file_extension = os.path.splitext(img.filename)[1]
            unique_filename = f"{uuid.uuid4()}{file_extension}"
            file_path = os.path.join(UPLOAD_DIR, unique_filename)
            
            with open(file_path, "wb") as buffer:
                content = await img.read()
                buffer.write(content)
            
            db_path = f"htmlfotos/{unique_filename}"
            image_urls.append(db_path)
            
            # --- KAPAK FOTOĞRAFI GÜNCELLEMESİ ---
            # İlk resmi ana tablo için seçiyoruz
            if index == 0:
                main_image_url = db_path

    # --- KONUM PARÇALAMA MANTIĞI ---
    loc_parts = [p.strip() for p in location.split(',')]
    district = loc_parts[0] if len(loc_parts) > 0 else ""
    city = loc_parts[1] if len(loc_parts) > 1 else ""
    country = loc_parts[2] if len(loc_parts) > 2 else ""

    # 2. Veritabanına Gönderilecek Veri
    # YENİ İŞ MANTIĞI UYUMU: Yeni ilanlar ilk kayıt esnasında onay havuzuna ('approving') düşecek şekilde statülendirildi.
    property_data = {
        "name": title, 
        "image": main_image_url, # Ana tabloya yazılacak kapak resmi
        "location": location,
        "district": district,
        "city": city,
        "country": country,
        "price": price, 
        "currency_code": currency_code, 
        "listing_type": listing_type, 
        "property_type": property_type, 
        "room_count": room_count,
        "gross_m2": gross_m2, 
        "net_m2": net_m2, 
        "building_age": building_age,
        "heating": heating, 
        "deed_status": deed_status, 
        "dues": dues,
        "description": description,
        "status": "approving"
    }

    # Özellik ID'lerinin tam sayı formatında db katmanına iletilmesini garanti altına alıyoruz
    valid_features = []
    for f in features:
        try:
            valid_features.append(int(f))
        except ValueError:
            continue

    success = db.add_full_property_to_db(agent_id, property_data, valid_features, image_urls)

    if success:
        return JSONResponse(content={"status": "success", "redirect": "/profile/properties"})
    else:
        return JSONResponse(status_code=500, content={"error": "Veritabanı kaydı başarısız oldu."})

# --- DİNAMİK İLAN GÜNCELLEME ENDPOINT'İ (YENİ EKLENDİ) ---
@router.post("/update-property/{property_id}")
async def update_property(
    property_id: str, # Güvenli string yakalama ve alt satırda int koruması yapıldı
    title: str = Form(...),
    location: str = Form(...),
    price: float = Form(...),
    currency_code: str = Form("TRY"),
    listing_type: str = Form("rent"),
    property_type: str = Form(None),
    room_count: str = Form(None),
    gross_m2: int = Form(0),
    net_m2: int = Form(0),
    building_age: str = Form(None),
    heating: str = Form(None),
    deed_status: str = Form(None),
    dues: float = Form(0),
    description: str = Form(""),
    features: List[str] = Form([])
):
    # Yetki Kontrolü: İlanı güncelleyen kişi giriş yapmış bir agent veya admin olmalı
    user_obj = getattr(db, 'current_user_data', None)
    if not user_obj or db.current_user_role not in ['agent', 'admin']:
        return JSONResponse(status_code=403, content={"error": "Bu işlem için yetkiniz yok."})

    # Veri tipi dönüşüm koruması
    clean_prop_id = int(property_id) if str(property_id).isdigit() else property_id

    # Eğer emlakçı ise ilanın kendisine ait olup olmadığını doğrulamak için mevcut ilanı çekiyoruz
    if db.current_user_role == 'agent':
        existing_prop = db.get_property_by_id(clean_prop_id)
        if not existing_prop or existing_prop.get('agent_id') != user_obj.get('id'):
            return JSONResponse(status_code=403, content={"error": "Sadece kendinize ait ilanları güncelleyebilirsiniz."})

    # Konum bilgilerini parçalama mantığı
    loc_parts = [p.strip() for p in location.split(',')]
    district = loc_parts[0] if len(loc_parts) > 0 else ""
    city = loc_parts[1] if len(loc_parts) > 1 else ""
    country = loc_parts[2] if len(loc_parts) > 2 else ""

    # Özellik listesini db katmanındaki int beklentisine tam uyumlu hale getiriyoruz
    valid_features = []
    for f in features:
        try:
            valid_features.append(int(f))
        except ValueError:
            continue

    update_data = {
        "name": title,
        "location": location,
        "district": district,
        "city": city,
        "country": country,
        "price": price,
        "currency_code": currency_code,
        "listing_type": listing_type,
        "property_type": property_type,
        "room_count": room_count,
        "gross_m2": gross_m2,
        "net_m2": net_m2,
        "building_age": building_age,
        "heating": heating,
        "deed_status": deed_status,
        "dues": dues,
        "description": description,
        "features": valid_features  # properties.py senkronizasyonu için int listesini ekledik
    }

    success = db.update_property_in_db(clean_prop_id, update_data)
    
    if success:
        redirect_path = "/admin/all-properties" if db.current_user_role == 'admin' else "/profile/properties"
        return JSONResponse(content={"status": "success", "redirect": redirect_path})
    else:
        return JSONResponse(status_code=500, content={"error": "Veritabanı güncelleme işlemi başarısız oldu."})

# --- MANTIKSAL SİLME (SOFT DELETE) ENDPOINT'İ (YENİ EKLENDİ) ---
@router.post("/delete-property/{property_id}")
async def delete_property(property_id: str):
    user_obj = getattr(db, 'current_user_data', None)
    if not user_obj or db.current_user_role not in ['agent', 'admin']:
        return JSONResponse(status_code=403, content={"error": "Bu işlem için yetkiniz yok."})

    clean_prop_id = int(property_id) if str(property_id).isdigit() else property_id

    if db.current_user_role == 'agent':
        existing_prop = db.get_property_by_id(clean_prop_id)
        if not existing_prop or existing_prop.get('agent_id') != user_obj.get('id'):
            return JSONResponse(status_code=403, content={"error": "Sadece kendinize ait ilanları silebilirsiniz."})

    success = db.delete_property_from_db(clean_prop_id)
    
    if success:
        redirect_path = "/admin/all-properties" if db.current_user_role == 'admin' else "/profile/properties"
        return JSONResponse(content={"status": "success", "redirect": redirect_path})
    else:
        return JSONResponse(status_code=500, content={"error": "İlan silme (pasife alma) işlemi başarısız oldu."})

# --- YÜKLEME ENDPOINT'İ (ESKİ - KORUNDU) ---
@router.post("/upload-property-image/{property_id}")
async def upload_property_image(property_id: str, file: UploadFile = File(...)):
    conn = db.get_db_connection()
    if not conn:
        return {"error": "DB Connection Error"}
    
    clean_prop_id = int(property_id) if str(property_id).isdigit() else property_id
    
    try:
        cur = conn.cursor()
        file_extension = os.path.splitext(file.filename)[1]
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        file_path = os.path.join(UPLOAD_DIR, unique_filename)
        
        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        db_path = f"htmlfotos/{unique_filename}"
        
        cur.execute(
            "INSERT INTO property_images (property_id, image_url) VALUES (%s, %s)",
            (clean_prop_id, db_path)
        )
        
        cur.execute("SELECT image FROM properties WHERE id = %s", (clean_prop_id,))
        row = cur.fetchone()
        
        if not row or row[0] in [None, "", "villa.png", "default.jpg"]:
            cur.execute(
                "UPDATE properties SET image = %s WHERE id = %s",
                (db_path, clean_prop_id)
            )

        conn.commit()
        cur.close()
        conn.close()
        
        return {
            "status": "success", 
            "message": "Fotoğraf başarıyla yüklendi",
            "url": db_path
        }
    except Exception as e:
        if conn: conn.rollback()
        print(f"Upload hatası: {e}")
        return {"error": str(e)}

# --- MEVCUT ROUTERLAR ---

@router.get("/home", response_class=HTMLResponse)
async def home(request: Request):
    properties_from_db = db.get_properties_from_db()
    current_properties = {str(p['id']): p for p in properties_from_db} if properties_from_db else {}
    
    popular_ids = ["1", "3", "5", "6", "8", "9"]
    popular_properties = []
    
    for pid in popular_ids:
        if pid in current_properties:
            item_copy = current_properties[pid].copy()
            processed = process_property_data(item_copy)
            popular_properties.append(processed)
    
    return templates.TemplateResponse(request, "home.html", {
        "properties": popular_properties, 
        "role": db.current_user_role, 
        "user": getattr(db, 'current_user_data', None),
        "page_id": "home"
    })

@router.get("/search", response_class=HTMLResponse)
async def search_page(request: Request, q: str = Query(None), page: int = Query(1, ge=1)):
    properties_from_db = db.get_properties_from_db()
    all_properties = properties_from_db if properties_from_db else []
    
    if q:
        all_properties = [
            p for p in all_properties 
            if q.lower() in str(p.get('name', '')).lower() or q.lower() in str(p.get('location', '')).lower()
        ]

    processed_properties = [process_property_data(p.copy()) for p in all_properties]
    
    items_per_page = 15
    total_items = len(processed_properties)
    total_pages = math.ceil(total_items / items_per_page) if total_items > 0 else 1
    
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    display_properties = processed_properties[start_idx:end_idx]
    
    return templates.TemplateResponse(request, "search.html", {
        "properties": display_properties, 
        "role": db.current_user_role, 
        "user": getattr(db, 'current_user_data', None),
        "page_id": "search",
        "current_page": page,
        "total_pages": total_pages,
        "query": q
    })

@router.get("/about", response_class=HTMLResponse)
async def about_page(request: Request):
    return templates.TemplateResponse(request, "about.html", {
        "role": db.current_user_role, 
        "user": getattr(db, 'current_user_data', None),
        "page_id": "about"
    })

@router.get("/property/{property_id}", response_class=HTMLResponse)
async def property_detail(request: Request, property_id: str):
    conn = db.get_db_connection()
    property_item = None
    property_features = []
    property_images = []
    agent_info = None

    # Neon DB Tipi için güvenli ID temizleme yapılıyor
    clean_id = int(property_id) if str(property_id).isdigit() else property_id

    if conn:
        try:
            from psycopg2.extras import RealDictCursor
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT * FROM properties WHERE id = %s", (clean_id,))
            property_item = cur.fetchone()
            
            if property_item:
                feature_query = """
                    SELECT f.name 
                    FROM features f
                    JOIN property_features pf ON f.id = pf.feature_id
                    WHERE pf.property_id = %s
                """
                cur.execute(feature_query, (clean_id,))
                property_features = [r['name'] for r in cur.fetchall()]

                cur.execute("SELECT image_url FROM property_images WHERE property_id = %s", (clean_id,))
                property_images = [r['image_url'] for r in cur.fetchall()]
                
                agent_info = db.get_property_agent_info(clean_id)
            
            cur.close()
            conn.close()
        except Exception as e:
            print(f"Veri çekme hatası: {e}")

    if not property_item: 
        return RedirectResponse(url="/home")

    property_item = process_property_data(property_item.copy())

    fields = ["room_count", "net_m2", "gross_m2", "dues", "property_type"]
    for field in fields:
        if property_item.get(field) is None:
            property_item[field] = "N/A" if field in ["room_count", "property_type"] else 0
        
    return templates.TemplateResponse(request, "desktop1.html", {
        "request": request, 
        "property": property_item,
        "property_features": property_features,
        "property_images": property_images,
        "agent": agent_info,
        "role": db.current_user_role, 
        "user": getattr(db, 'current_user_data', None),
        "page_id": "search"
    })

# --- MY PROPERTIES (PROFİL) ROUTER'I ---

@router.get("/profile/properties", response_class=HTMLResponse)
async def my_properties(request: Request, page: int = Query(1, ge=1)):
    # Kullanıcı objesi tespiti
    user_obj = getattr(db, 'current_user_data', None)
    current_agent_id = user_obj.get("id") if user_obj else None
    
    # EMALAKÇI GÜVENLİK FİLTRESİ:
    # Emlakçının kendi yönetim panelinde 'approving' (onay bekleyen) ilanlarını da listeleyebilmesi için 
    # db katmanındaki özel portföy çekme fonksiyonunu kullanıyoruz.
    if current_agent_id and hasattr(db, 'get_agent_with_properties'):
        _, my_props_raw = db.get_agent_with_properties(current_agent_id)
    else:
        properties_from_db = db.get_properties_from_db()
        my_props_raw = [p for p in properties_from_db if p.get('agent_id') == current_agent_id]
        
    all_my_properties = [process_property_data(p.copy()) for p in my_props_raw]
    
    items_per_page = 12
    total_items = len(all_my_properties)
    total_pages = math.ceil(total_items / items_per_page) if total_items > 0 else 1
    
    page = max(1, min(page, total_pages))
    
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    display_properties = all_my_properties[start_idx:end_idx]
    
    u_image = "default_user.png"
    u_first = ""
    u_last = ""
    u_role = db.current_user_role or "user"

    if user_obj and isinstance(user_obj, dict):
        raw_img = user_obj.get("profile_image") or "default_user.png"
        u_image = str(raw_img).split('/')[-1] if "/" in str(raw_img) else str(raw_img)
        u_first = user_obj.get("first_name") or ""
        u_last = user_obj.get("last_name") or ""

    return templates.TemplateResponse(request, "properties.html", {
        "request": request,
        "properties": display_properties,
        "current_page": page,
        "total_pages": total_pages,
        "role": u_role,
        "profile_image": u_image, 
        "first_name": u_first,    
        "last_name": u_last,      
        "p_page": "properties",   
        "user": user_obj
    })