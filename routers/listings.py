from fastapi import APIRouter, Request, Query, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
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
    return symbols.get(code, '₺')

def process_property_data(property_item):
    """
    İlan verisini HTML'de kullanılabilir hale getirmek için 
    fiyat, sembol ve formatlama işlemlerini yapar.
    """
    if not property_item:
        return None
        
    raw_type = property_item.get("type") or property_item.get("listing_type", "rent")
    p_type = str(raw_type).lower()
    
    if p_type in ["sale", "satılık"]:
        property_item["display_type"] = "FOR SALE"
        property_item["is_sale"] = True
        raw_price = property_item.get("price_normalized")
    else:
        property_item["display_type"] = "FOR RENT"
        property_item["is_sale"] = False
        raw_price = property_item.get("monthly_price")
        
    if raw_price is None or str(raw_price) == "0" or raw_price == "":
        raw_price = property_item.get("price", 0)

    try:
        price_float = float(raw_price) if raw_price else 0
        if price_float > 0:
            property_item["formatted_price"] = format_currency(price_float)
        else:
            property_item["formatted_price"] = None 
    except:
        property_item["formatted_price"] = None
    
    curr_code = property_item.get("currency", "TRY")
    property_item["currency_symbol"] = get_currency_symbol(curr_code)

    if "dues" in property_item and property_item["dues"] not in [None, "N/A"]:
        property_item["formatted_dues"] = format_currency(property_item["dues"])
    
    # property_type kolonu db'den gelmişse capitalize ediyoruz
    if "property_type" in property_item and property_item["property_type"]:
        property_item["property_type"] = str(property_item["property_type"]).capitalize()
    
    return property_item

# Jinja2 filtresi olarak kaydet
templates.env.filters["currency"] = format_currency

# --- YÜKLEME ENDPOINT'İ (Tekli Yükleme & Akıllı Kapak Fotoğrafı) ---

@router.post("/upload-property-image/{property_id}")
async def upload_property_image(property_id: int, file: UploadFile = File(...)):
    """Seçilen fotoğrafı kaydeder, DB'ye bağlar ve gerekirse kapak fotoğrafı yapar."""
    conn = db.get_db_connection()
    if not conn:
        return {"error": "DB Connection Error"}
    
    try:
        cur = conn.cursor()
        
        # 1. Dosya işlemleri
        file_extension = os.path.splitext(file.filename)[1]
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        file_path = os.path.join(UPLOAD_DIR, unique_filename)
        
        # Fiziksel kayıt
        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        db_path = f"htmlfotos/{unique_filename}"
        
        # 2. Veritabanına (property_images tablosuna) kayıt
        cur.execute(
            "INSERT INTO property_images (property_id, image_url) VALUES (%s, %s)",
            (property_id, db_path)
        )
        
        # 3. OTOMATİK KAPAK FOTOĞRAFI KONTROLÜ
        # properties tablosundaki mevcut 'image' değerini kontrol et
        cur.execute("SELECT image FROM properties WHERE id = %s", (property_id,))
        row = cur.fetchone()
        
        # Eğer ana resim yoksa veya varsayılan değerdeyse, bu yüklenen ilk resmi kapak yap
        if not row or row[0] in [None, "", "villa.png", "default.jpg"]:
            cur.execute(
                "UPDATE properties SET image = %s WHERE id = %s",
                (unique_filename, property_id)
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
    current_properties = {str(p['id']): p for p in properties_from_db} if properties_from_db else db.properties
    
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
        "page_id": "home"
    })

@router.get("/search", response_class=HTMLResponse)
async def search_page(request: Request, q: str = Query(None), page: int = Query(1, ge=1)):
    properties_from_db = db.get_properties_from_db()
    all_properties = properties_from_db if properties_from_db else list(db.properties.values())
    
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
        "page_id": "search",
        "current_page": page,
        "total_pages": total_pages,
        "query": q
    })

@router.get("/about", response_class=HTMLResponse)
async def about_page(request: Request):
    return templates.TemplateResponse(request, "about.html", {
        "role": db.current_user_role, 
        "page_id": "about"
    })

@router.get("/aichat", response_class=HTMLResponse)
async def aichat_page(request: Request):
    return templates.TemplateResponse(request, "search.html", {
        "properties": [], 
        "role": db.current_user_role, 
        "page_id": "aichat"
    })

@router.get("/property/{property_id}", response_class=HTMLResponse)
async def property_detail(request: Request, property_id: str):
    conn = db.get_db_connection()
    property_item = None
    property_features = []
    property_images = []
    agent_info = None  # Agent bilgisi için değişkeni tanımladık

    if conn:
        try:
            cur = conn.cursor(cursor_factory=db.RealDictCursor)
            cur.execute("SELECT * FROM properties WHERE id = %s", (property_id,))
            property_item = cur.fetchone()
            
            if property_item:
                # 1. Özellikleri çek
                feature_query = """
                    SELECT f.name 
                    FROM features f
                    JOIN property_features pf ON f.id = pf.feature_id
                    WHERE pf.property_id = %s
                """
                cur.execute(feature_query, (property_id,))
                property_features = [r['name'] for r in cur.fetchall()]

                # 2. Resimleri çek
                cur.execute("SELECT image_url FROM property_images WHERE property_id = %s", (property_id,))
                property_images = [r['image_url'] for r in cur.fetchall()]
                
                # 3. YENİ: Agent (Emlakçı) Bilgilerini Çek (Dinamik)
                # database.py'da yeni yazdığımız fonksiyonu çağırıyoruz
                agent_info = db.get_property_agent_info(property_id)
            
            cur.close()
            conn.close()
        except Exception as e:
            print(f"Veri çekme hatası: {e}")

    if not property_item:
        property_item = db.properties.get(property_id)
        if property_item and not property_features:
            property_features = ["Free WiFi", "Air Conditioning", "Parking"]
        if property_item and not property_images:
            property_images = [property_item.get("image", "villa.png")]

    if not property_item: 
        return RedirectResponse(url="/home")

    property_item = process_property_data(property_item.copy())

    fields = ["room_count", "net_m2", "gross_m2", "dues", "property_type"]
    for field in fields:
        if property_item.get(field) is None:
            if field == "room_count":
                property_item[field] = "N/A"
            elif field == "property_type":
                property_item[field] = "Villa"
            else:
                property_item[field] = 0
        
    return templates.TemplateResponse(request, "desktop1.html", {
        "request": request,  # Request nesnesini her ihtimale karşı ekledik
        "property": property_item,
        "property_features": property_features,
        "property_images": property_images,
        "agent": agent_info,  # HTML kartındaki Melih Nitiş verileri buradan gidecek
        "role": db.current_user_role, 
        "page_id": "search"
    })