from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import database as db
import math

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# --- YARDIMCI FONKSİYONLAR ---

def format_currency(value):
    """Sayıyı binlik ayracı (nokta) ile formatlar."""
    try:
        if value is None or value == "" or value == "None":
            return "0"
        # Float'a çevirip kontrol et, 0 ise 0 döndür
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
        
    # 'type' veya 'listing_type' kolonunu kontrol et
    raw_type = property_item.get("type") or property_item.get("listing_type", "rent")
    p_type = str(raw_type).lower()
    
    # 1. ETİKET VE TÜR BELİRLEME (FOR RENT / FOR SALE)
    # Veritabanı yapına göre fiyat sütunlarını eşliyoruz
    if p_type in ["sale", "satılık"]:
        property_item["display_type"] = "FOR SALE"
        property_item["is_sale"] = True
        # Satılıklar için ana kaynak: price_normalized
        raw_price = property_item.get("price_normalized")
    else:
        property_item["display_type"] = "FOR RENT"
        property_item["is_sale"] = False
        # Kiralıklar için ana kaynak: monthly_price
        raw_price = property_item.get("monthly_price")
        
    # Eğer belirlenen sütunlar boş veya 0 ise genel 'price' sütununa bak
    if raw_price is None or str(raw_price) == "0" or raw_price == "":
        raw_price = property_item.get("price", 0)

    # 2. FORMATLAMA
    # Nihai fiyatı kontrol et, 0'dan büyükse formatla
    try:
        price_float = float(raw_price) if raw_price else 0
        if price_float > 0:
            property_item["formatted_price"] = format_currency(price_float)
        else:
            property_item["formatted_price"] = None # HTML'de "Price on Request" basılması için
    except:
        property_item["formatted_price"] = None
    
    # Currency (Döviz) kontrolü
    curr_code = property_item.get("currency", "TRY")
    property_item["currency_symbol"] = get_currency_symbol(curr_code)

    # Aidat (Dues) Formatlama (Yeni eklendi)
    if "dues" in property_item and property_item["dues"] not in [None, "N/A"]:
        property_item["formatted_dues"] = format_currency(property_item["dues"])
    
    return property_item

# Jinja2 filtresi olarak kaydet
templates.env.filters["currency"] = format_currency

@router.get("/home", response_class=HTMLResponse)
async def home(request: Request):
    # Veritabanından verileri çek
    properties_from_db = db.get_properties_from_db()
    
    # Yedek mekanizması
    current_properties = {str(p['id']): p for p in properties_from_db} if properties_from_db else db.properties
    
    # Popüler ilanlar listesi
    popular_ids = ["1", "3", "5", "6", "8", "9"]
    popular_properties = []
    
    for pid in popular_ids:
        if pid in current_properties:
            # Orijinal veriyi bozmamak için kopya üzerinden işlem yapıyoruz
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
    # Verileri çek
    properties_from_db = db.get_properties_from_db()
    all_properties = properties_from_db if properties_from_db else list(db.properties.values())
    
    # Arama (Query) filtresi
    if q:
        all_properties = [
            p for p in all_properties 
            if q.lower() in str(p.get('name', '')).lower() or q.lower() in str(p.get('location', '')).lower()
        ]

    # Her bir ilanı işle (fiyat ve sembol formatı)
    processed_properties = [process_property_data(p.copy()) for p in all_properties]
    
    # SAYFALAMA MANTIĞI
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

    if conn:
        try:
            cur = conn.cursor(cursor_factory=db.RealDictCursor)
            # Mülk bilgilerini çek
            cur.execute("SELECT * FROM properties WHERE id = %s", (property_id,))
            property_item = cur.fetchone()
            
            if property_item:
                # Özellikleri (features) getir - junction table üzerinden isimleri çekiyoruz
                feature_query = """
                    SELECT f.name 
                    FROM features f
                    JOIN property_features pf ON f.id = pf.feature_id
                    WHERE pf.property_id = %s
                """
                cur.execute(feature_query, (property_id,))
                rows = cur.fetchall()
                # Özellik isimlerini listeye atıyoruz
                property_features = [r['name'] for r in rows]
            
            cur.close()
            conn.close()
        except Exception as e:
            print(f"Veri çekme hatası: {e}")

    # Yedek mekanizması (DB'de yoksa statik dataya bak)
    if not property_item:
        property_item = db.properties.get(property_id)
        if property_item and not property_features:
            # Statik veride özellik yoksa varsayılanlar
            property_features = ["Free WiFi", "Air Conditioning", "Parking"]

    if not property_item: 
        return RedirectResponse(url="/home")

    # Veriyi işle (fiyat formatı, semboller vb.)
    property_item = process_property_data(property_item.copy())

    # Güvenlik Kontrolleri (N/A değerler ve Dues kontrolü)
    fields = ["room_count", "net_m2", "gross_m2", "dues"]
    for field in fields:
        if property_item.get(field) is None:
            property_item[field] = "N/A" if field == "room_count" else 0
        
    return templates.TemplateResponse(request, "desktop1.html", {
        "property": property_item,
        "property_features": property_features, # HTML'de bu ismi kullanacağız
        "role": db.current_user_role, 
        "page_id": "search"
    })