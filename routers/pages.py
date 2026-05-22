import math
from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from psycopg2.extras import RealDictCursor
import database as db

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# --- YARDIMCI FONKSİYONLAR ---
def format_currency(value):
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
    symbols = {'TRY': '₺', 'USD': '$', 'EUR': '€', 'GBP': '£'}
    return symbols.get(str(code).upper(), '₺')

def process_property_data(property_item):
    if not property_item:
        return None
    raw_image = property_item.get("image")
    property_item["image"] = str(raw_image).strip() if raw_image else "htmlfotos/default.jpg"
    
    raw_type = property_item.get("listing_type") or property_item.get("type", "rent")
    if str(raw_type).lower() in ["sale", "satılık"]:
        property_item["display_type"] = "FOR SALE"
        property_item["is_sale"] = True
    else:
        property_item["display_type"] = "FOR RENT"
        property_item["is_sale"] = False

    raw_price = property_item.get("price_normalized") or property_item.get("price", 0)
    try:
        property_item["formatted_price"] = format_currency(float(raw_price))
    except:
        property_item["formatted_price"] = "0"

    curr_code = property_item.get("currency_code") or property_item.get("currency", "TRY")
    property_item["currency_symbol"] = get_currency_symbol(curr_code)

    # Senkronizasyonlar
    if 'name' in property_item and not property_item.get('title'): property_item['title'] = property_item['name']
    if 'title' in property_item and not property_item.get('name'): property_item['name'] = property_item['title']
    
    property_item["net_m2"] = property_item.get("net_m2") or 0
    property_item["room_count"] = property_item.get("room_count") or "3+1"
    property_item["dues"] = property_item.get("dues") or 0
    if "dues" in property_item:
        property_item["formatted_dues"] = format_currency(property_item["dues"])
    return property_item

templates.env.filters["currency"] = format_currency

# --- SAYFA ROTALARI ---

@router.get("/home", response_class=HTMLResponse)
async def home(request: Request):
    properties_from_db = db.get_properties_from_db()
    current_properties = {str(p['id']): p for p in properties_from_db} if properties_from_db else {}
    popular_ids = ["1", "3", "5", "6", "8", "9"]
    popular_properties = []
    for pid in popular_ids:
        if pid in current_properties:
            item_copy = current_properties[pid].copy()
            popular_properties.append(process_property_data(item_copy))
    return templates.TemplateResponse(request, "home.html", {
        "properties": popular_properties, "page_id": "home"
    })

@router.get("/search", response_class=HTMLResponse)
async def search_page(request: Request, q: str = Query(None), page: int = Query(1, ge=1)):
    properties_from_db = db.get_properties_from_db()
    all_properties = properties_from_db if properties_from_db else []
    if q:
        all_properties = [p for p in all_properties if q.lower() in str(p.get('name', '')).lower() or q.lower() in str(p.get('location', '')).lower()]
    
    processed_properties = [process_property_data(p.copy()) for p in all_properties]
    items_per_page = 15
    total_pages = math.ceil(len(processed_properties) / items_per_page) if processed_properties else 1
    start_idx = (page - 1) * items_per_page
    display_properties = processed_properties[start_idx:start_idx + items_per_page]
    
    return templates.TemplateResponse(request, "search.html", {
        "properties": display_properties, "page_id": "search", "current_page": page, "total_pages": total_pages, "query": q
    })

@router.get("/about", response_class=HTMLResponse)
async def about_page(request: Request):
    return templates.TemplateResponse(request, "about.html", {"page_id": "about"})

@router.get("/property/{property_id}", response_class=HTMLResponse)
async def property_detail(request: Request, property_id: str):
    conn = db.get_db_connection()
    property_item, property_features, property_images, agent_info = None, [], [], None
    clean_id = int(property_id) if str(property_id).isdigit() else property_id
    if conn:
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT * FROM properties WHERE id = %s", (clean_id,))
            property_item = cur.fetchone()
            if property_item:
                cur.execute("SELECT f.name FROM features f JOIN property_features pf ON f.id = pf.feature_id WHERE pf.property_id = %s", (clean_id,))
                property_features = [r['name'] for r in cur.fetchall()]
                cur.execute("SELECT image_url FROM property_images WHERE property_id = %s", (clean_id,))
                property_images = [r['image_url'] for r in cur.fetchall()]
                agent_info = db.get_property_agent_info(clean_id)
            cur.close()
            conn.close()
        except Exception as e:
            print(f"Detay çekme hatası: {e}")
            
    if not property_item:
        return RedirectResponse(url="/home")
        
    property_item = process_property_data(property_item.copy())
    return templates.TemplateResponse(request, "desktop1.html", {
        "property": property_item, "property_features": property_features,
        "property_images": property_images, "agent": agent_info, "page_id": "search"
    })