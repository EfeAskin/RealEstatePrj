import math
from typing import Optional, List
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from psycopg2.extras import RealDictCursor
import database as db

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# --- GÖRSEL VE PARA FORMATLAMA YARDIMCILARI ---

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
    """Veritabanından gelen veriyi HTML şablonunun beklediği formata sokar."""
    if not property_item:
        return None
        
    # Resim kontrolü
    raw_image = property_item.get("image")
    if raw_image:
        property_item["image"] = str(raw_image).strip()
    else:
        property_item["image"] = "htmlfotos/default.jpg"
        
    # Satılık / Kiralık Etiketi (listing_type altında sale ve rent kontrolü)
# --- 1. KISIM (GÜNCEL DURUM): SADECE LISTING_TYPE KONTROLÜ ---
    raw_type = property_item.get("listing_type")
    p_type = str(raw_type).lower().strip() if raw_type else ""
    
    if p_type in ["sale", "satılık", "satilik"]:
        property_item["display_type"] = "FOR SALE"
        property_item["is_sale"] = True
    elif p_type in ["rent", "kiralık", "kiralik"]:
        property_item["display_type"] = "FOR RENT"
        property_item["is_sale"] = False
    else:
        property_item["display_type"] = "PROPERTIES"
        property_item["is_sale"] = False
    # -------------------------------------------------------------
    
    # Fiyat ve Para Birimi Ayarları
    raw_price = property_item.get("price_normalized")
    if raw_price is None or str(raw_price) == "0" or raw_price == "":
        raw_price = property_item.get("price", 0)

    try:
        price_float = float(raw_price) if raw_price else 0
        property_item["formatted_price"] = format_currency(price_float)
    except:
        property_item["formatted_price"] = "0"
        
    curr_code = property_item.get("currency_code") or property_item.get("currency") or "TRY"
    property_item["currency_symbol"] = get_currency_symbol(curr_code)

    # İsim - Başlık Senkronizasyonu
    if 'name' in property_item and not property_item.get('title'):
        property_item['title'] = property_item['name']
    if 'title' in property_item and not property_item.get('name'):
        property_item['name'] = property_item['title']

    # Varsayılan Değer Atamaları
    property_item["net_m2"] = property_item.get("net_m2") or 0
    property_item["gross_m2"] = property_item.get("gross_m2") or 0
    property_item["open_m2"] = property_item.get("open_m2") or 0
    property_item["room_count"] = property_item.get("room_count") or "3+1"
    property_item["building_age"] = property_item.get("building_age") or "0"
    property_item["heating"] = property_item.get("heating") or "Yok"
    property_item["location"] = property_item.get("location") or property_item.get("district", "N/A")

    if "dues" in property_item and property_item["dues"] not in [None, "N/A"]:
        property_item["formatted_dues"] = format_currency(property_item["dues"])
    else:
        property_item["formatted_dues"] = "0"
        
    return property_item

if "currency" not in templates.env.filters:
    templates.env.filters["currency"] = format_currency


# --- %100 UYUMLU GELİŞMİŞ FİLTRELEME MOTORU ---

@router.get("/search", response_class=HTMLResponse)
async def dynamic_search_filter_engine(
    request: Request,
    page: int = Query(1, alias="page", ge=1),
    q: Optional[str] = Query(None),
    listing_type: Optional[str] = Query(None, alias="type"),
    property_type: Optional[str] = Query(None, alias="property_type"),
    min_price: Optional[float] = Query(None),
    max_price: Optional[float] = Query(None),
    currency: Optional[str] = Query(None),
    room_count: Optional[str] = Query(None, alias="rooms"),
    bath_count: Optional[str] = Query(None, alias="baths"),
    min_net_m2: Optional[int] = Query(None),
    max_net_m2: Optional[int] = Query(None),
    min_gross_m2: Optional[int] = Query(None),
    max_gross_m2: Optional[int] = Query(None),
    min_open_m2: Optional[int] = Query(None),
    max_open_m2: Optional[int] = Query(None),
    building_age: Optional[str] = Query(None),
    heating: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    district: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
    is_site: Optional[str] = Query(None),
    credit: Optional[str] = Query(None),
    swap: Optional[str] = Query(None),
    property_status: Optional[str] = Query(None),
    title_type: Optional[str] = Query(None),
    furniture: Optional[str] = Query(None),
    otopark: Optional[str] = Query(None),
    features: Optional[str] = Query(None)
):
    user_id_cookie = request.cookies.get("user_id")
    user_obj = db.get_user_from_cookie(user_id_cookie) if user_id_cookie else None
    user_role = user_obj.get("role", "guest") if user_obj else "guest"

    all_features_list = []
    conn = db.get_db_connection()
    
    if not conn:
        return templates.TemplateResponse(request, "search.html", {
            "properties": [], "properties_from_db": [], "all_features": [],
            "total_pages": 1, "current_page": 1, "query": q or "",
            "selected_type": listing_type or "", "role": user_role, "user": user_obj, "page_id": "search", "filters": {}
        })

    all_filtered_rows = []
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, name FROM features ORDER BY name ASC")
        all_features_list = cur.fetchall()

        query = "SELECT * FROM properties WHERE status = 'active'"
        params = []

        # 1. Metin Arama
        if q and q.strip():
            query += " AND (name ILIKE %s OR location ILIKE %s OR description ILIKE %s)"
            search_param = f"%{q.strip()}%"
            params.extend([search_param, search_param, search_param])

        # 2. Listing Type (sale / rent Kayıt Kontrolü)
# --- 2. KISIM (DÜZELTİLMİŞ): SADECE LISTING_TYPE KULLANAN SQL FİLTRESİ ---
        if listing_type and listing_type.strip():
            l_type = listing_type.strip().lower()
            
            # 'mix', 'all' veya boş ise filtre eklemiyoruz (böylece hepsi geliyor)
            if l_type not in ["mix", "all", ""]:
                if l_type in ["rent", "kiralık", "kiralik"]:
                    # Hatalı olan 'type' sütunu kaldırıldı, sadece var olan 'listing_type' sorgulanıyor
                    query += " AND LOWER(listing_type) IN ('rent', 'kiralık', 'kiralik')"
                elif l_type in ["sale", "satılık", "satilik"]:
                    # Hatalı olan 'type' sütunu kaldırıldı, sadece var olan 'listing_type' sorgulanıyor
                    query += " AND LOWER(listing_type) IN ('sale', 'satılık', 'satilik')"
                else:
                    query += " AND LOWER(listing_type) = %s"
                    params.append(l_type)
        # -------------------------------------------------------------------------

        # 3. Property Type
        if property_type and property_type.strip() and property_type != "all":
            query += " AND property_type = %s"
            params.append(property_type.strip())

        # 4. Fiyat Aralıkları (Güvenli Cast)
        if min_price is not None:
            query += " AND (price_normalized >= %s OR (CASE WHEN price ~ '^[0-9.]+$' THEN price::numeric ELSE 0 END) >= %s)"
            params.extend([min_price, min_price])
        if max_price is not None:
            query += " AND (price_normalized <= %s OR (CASE WHEN price ~ '^[0-9.]+$' THEN price::numeric ELSE 0 END) <= %s)"
            params.extend([max_price, max_price])

        # 5. Currency
        if currency and currency.strip() and currency != "all":
            query += " AND (currency_code = %s OR currency = %s)"
            params.extend([currency.strip(), currency.strip()])

        # 6. Room Count & Bath Count
        if room_count and room_count.strip() and room_count != "all":
            query += " AND room_count = %s"
            params.append(room_count.strip())
        if bath_count and bath_count.strip() and bath_count != "all":
            query += " AND (bath_count = %s OR bath_count::text = %s)"
            params.extend([bath_count.strip(), bath_count.strip()])

        # 7. Metrekareler
        if min_net_m2 is not None: query += " AND net_m2 >= %s"; params.append(min_net_m2)
        if max_net_m2 is not None: query += " AND net_m2 <= %s"; params.append(max_net_m2)
        if min_gross_m2 is not None: query += " AND gross_m2 >= %s"; params.append(min_gross_m2)
        if max_gross_m2 is not None: query += " AND gross_m2 <= %s"; params.append(max_gross_m2)
        if min_open_m2 is not None: query += " AND open_m2 >= %s"; params.append(min_open_m2)
        if max_open_m2 is not None: query += " AND open_m2 <= %s"; params.append(max_open_m2)

        # 8. Building Age & Heating
        if building_age and building_age.strip() and building_age != "all":
            query += " AND building_age = %s"
            params.append(building_age.strip())
        if heating and heating.strip() and heating != "all":
            query += " AND heating = %s"
            params.append(heating.strip())

        # 9. Coğrafi Filtreler
        if country and country.strip() and country != "all":
            query += " AND country = %s"
            params.append(country.strip())
        if city and city.strip() and city != "all":
            query += " AND city = %s"
            params.append(city.strip())
        if district and district.strip() and district != "all":
            query += " AND (district = %s OR location ILIKE %s)"
            params.extend([district.strip(), f"%{district.strip()}%"])

        # 10. Boolean / Yan Alan Seçenekleri
        if is_site and is_site.strip().lower() == "yes": query += " AND (is_site = TRUE OR is_site = 'Evet' OR is_site = 'yes')"
        elif is_site and is_site.strip().lower() == "no": query += " AND (is_site = FALSE OR is_site = 'Hayır' OR is_site = 'no')"
        if credit and credit.strip().lower() == "yes": query += " AND (credit = TRUE OR credit = 'Evet' OR credit = 'yes')"
        elif credit and credit.strip().lower() == "no": query += " AND (credit = FALSE OR credit = 'Hayır' OR credit = 'no')"
        if swap and swap.strip().lower() == "yes": query += " AND (swap = TRUE OR swap = 'Evet' OR swap = 'yes')"
        elif swap and swap.strip().lower() == "no": query += " AND (swap = FALSE OR swap = 'Hayır' OR swap = 'no')"

        # 11. Property Status (Emlak Durumu Tamiri)
        if property_status and property_status.strip() and property_status != "all":
            query += " AND property_status = %s"
            params.append(property_status.strip())

        # Orijinal Ekstra Alan Filtreleri (Dokunulmadı)
        if title_type and title_type.strip() and title_type != "all":
            query += " AND title_type = %s"; params.append(title_type.strip())
        if furniture and furniture.strip() and furniture != "all":
            query += " AND furniture = %s"; params.append(furniture.strip())
        if otopark and otopark.strip() and otopark != "all":
            query += " AND otopark = %s"; params.append(otopark.strip())

        # 12. Multiple Features Checkbox Mantığı
        if features and features.strip():
            try:
                feature_ids = [int(x.strip()) for x in features.split(",") if x.strip().isdigit()]
                if feature_ids:
                    placeholder = ",".join(["%s"] * len(feature_ids))
                    sub_query = f"SELECT property_id FROM property_features WHERE feature_id IN ({placeholder}) GROUP BY property_id HAVING COUNT(DISTINCT feature_id) = %s"
                    query += f" AND id IN ({sub_query})"
                    params.extend(feature_ids + [len(feature_ids)])
            except Exception as fe:
                print(f"Feature filter error: {fe}")

        # 13. SORT BY SORTING MOTORU (Neon DB Güvenli Yapı)
# --- GÜNCELLENMİŞ SIRALAMA (SORT BY) SORGUSU ---   #ilerde price normalize ve when ... kısmını güncelleyi döviz kurlarına bağlı olarak sıralama yapıclak
        if sort:
            sort_str = str(sort).strip().lower()
            
            if "high to low" in sort_str or "yüksek" in sort_str:
                query += " ORDER BY COALESCE(price_normalized, 0) DESC, id DESC"
            elif "low to high" in sort_str or "düşük" in sort_str:
                query += " ORDER BY COALESCE(price_normalized, 0) ASC, id DESC"
            elif "oldest" in sort_str or "eski" in sort_str or "old" in sort_str:
                query += " ORDER BY id ASC"  # id ASC olduğu için ilk eklenen (en eski) ilanlar en başta gelir
            else:
                query += " ORDER BY id DESC"
        else:
            query += " ORDER BY id DESC"
        # -----------------------------------------------------

        cur.execute(query, tuple(params))
        all_filtered_rows = cur.fetchall()
        cur.close()
    except Exception as e:
        print(f"Neon DB SQL Error: {e}")
        all_filtered_rows = []
    finally:
        conn.close()

    processed_properties = [process_property_data(p.copy()) for p in all_filtered_rows if p]
    
    items_per_page = 15
    total_items = len(processed_properties)
    total_pages = math.ceil(total_items / items_per_page) if total_items > 0 else 1
    page = max(1, min(page, total_pages))
    
    start_idx = (page - 1) * items_per_page
    display_properties = processed_properties[start_idx : start_idx + items_per_page]

    active_filters = {
        "q": q or "", "listing_type": listing_type or "all", "property_type": property_type or "all",
        "min_price": min_price if min_price is not None else "", "max_price": max_price if max_price is not None else "",
        "currency": currency or "all", "rooms": room_count or "all", "baths": bath_count or "all",
        "min_net_m2": min_net_m2 if min_net_m2 is not None else "", "max_net_m2": max_net_m2 if max_net_m2 is not None else "",
        "min_gross_m2": min_gross_m2 if min_gross_m2 is not None else "", "max_gross_m2": max_gross_m2 if max_gross_m2 is not None else "",
        "min_open_m2": min_open_m2 if min_open_m2 is not None else "", "max_open_m2": max_open_m2 if max_open_m2 is not None else "",
        "building_age": building_age or "all", "heating": heating or "all", "country": country or "all",
        "city": city or "all", "district": district or "all", "sort": sort or "Latest", "is_site": is_site or "",
        "credit": credit or "", "swap": swap or "", "property_status": property_status or "",
        "title_type": title_type or "", "furniture": furniture or "", "otopark": otopark or "", "features": features or ""
    }

    return templates.TemplateResponse(request, "search.html", {
        "properties": display_properties, "properties_from_db": display_properties, "all_features": all_features_list,
        "current_page": page, "total_pages": total_pages, "query": q or "", "selected_type": listing_type or "",
        "min_price": min_price if min_price is not None else "", "max_price": max_price if max_price is not None else "",
        "property_type": property_type or "", "rooms": room_count or "", "baths": bath_count or "",
        "country": country or "", "city": city or "", "district": district or "", "currency": currency or "",
        "min_net_m2": min_net_m2 if min_net_m2 is not None else "", "max_net_m2": max_net_m2 if max_net_m2 is not None else "",
        "min_gross_m2": min_gross_m2 if min_gross_m2 is not None else "", "max_gross_m2": max_gross_m2 if max_gross_m2 is not None else "",
        "min_open_m2": min_open_m2 if min_open_m2 is not None else "", "max_open_m2": max_open_m2 if max_open_m2 is not None else "",
        "building_age": building_age or "", "heating": heating or "", "is_site": is_site or "", "credit": credit or "",
        "swap": swap or "", "property_status": property_status or "", "title_type": title_type or "", "furniture": furniture or "",
        "otopark": otopark or "", "selected_features": features or "", "sort_param": sort or "Latest",
        "role": user_role, "user": user_obj, "page_id": "search", "filters": active_filters
    })