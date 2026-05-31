import math
from typing import Optional, List
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from psycopg2.extras import RealDictCursor
import database as db
from services import ai_config, openai_client, query_pipeline, constraint_extractor
from services import currency as currency_svc  # aliased: 'currency' is a query param below
from services.place_aliases import normalize_places

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# Özellik (features) listesi için süreç-içi önbellek (nadiren değişir)
_features_cache = {"at": 0.0, "data": None}

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
def dynamic_search_filter_engine(
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
        # Özellik listesi nadiren değişir -> kısa süreli önbellek (her aramada sorgu yok)
        import time as _t
        if _features_cache["data"] and _t.time() - _features_cache["at"] < 300:
            all_features_list = _features_cache["data"]
        else:
            cur.execute("SELECT id, name FROM features ORDER BY name ASC")
            all_features_list = cur.fetchall()
            _features_cache.update(at=_t.time(), data=all_features_list)

        query = "SELECT * FROM properties WHERE status = 'active'"
        params = []

        # 1. Doğal Dil / Metin Arama — AI GPT HARD-FILTERS + semantic ranking.
        # When AI is on, parse the free-text query into structured constraints
        # (listing_type / property_type / city / district / beds / price) and apply
        # them as real WHERE filters — but only for fields the user did NOT already set
        # via the dropdowns (UI takes precedence). Price is currency-aware: mixed-currency
        # rows are normalized to USD with live cached rates. Ordering happens later in the
        # vector rerank. Without AI, falls back to keyword ILIKE.
        gpt_filters = None
        if q and q.strip():
            if ai_config.ai_enabled():
                try:
                    gpt_filters = constraint_extractor.extract(normalize_places(q.strip()))
                except Exception as ex:
                    print(f"GPT extract skipped: {ex}")
                    gpt_filters = None

            if gpt_filters is not None:
                _ui_unset = lambda v: (not v) or str(v).strip().lower() in ("", "all", "mix")

                if _ui_unset(listing_type) and gpt_filters.get("listing_type"):
                    query += " AND LOWER(listing_type) = %s"
                    params.append(gpt_filters["listing_type"])
                if _ui_unset(property_type) and gpt_filters.get("property_type"):
                    query += " AND property_type = %s"
                    params.append(gpt_filters["property_type"])
                # Match the SAME place across columns (flat free-text geography):
                # a place may sit in city/district/location on otherwise-matching
                # rows. Case-insensitive, still strict (exact value, no wildcards
                # except the longer free-text `location`). Mirrors build_candidate_sql.
                if _ui_unset(city) and gpt_filters.get("city"):
                    query += " AND (city ILIKE %s OR district ILIKE %s)"
                    params.extend([gpt_filters["city"], gpt_filters["city"]])
                if _ui_unset(district) and gpt_filters.get("district"):
                    query += " AND (district ILIKE %s OR city ILIKE %s OR location ILIKE %s)"
                    params.extend([gpt_filters["district"], gpt_filters["district"],
                                   f"%{gpt_filters['district']}%"])
                if gpt_filters.get("min_beds") is not None:
                    query += " AND beds >= %s"
                    params.append(gpt_filters["min_beds"])
                if gpt_filters.get("max_beds") is not None:
                    query += " AND beds <= %s"
                    params.append(gpt_filters["max_beds"])

                # currency-aware price (only if the UI price fields are empty)
                if (min_price is None and max_price is None) and (
                    gpt_filters.get("min_price") is not None or gpt_filters.get("max_price") is not None
                ):
                    rates = currency_svc.get_usd_rates()
                    qcur = gpt_filters.get("currency") or "USD"
                    # converts each listing's price_normalized to USD inside one CASE expr
                    case_expr = ("price_normalized * CASE UPPER(COALESCE(currency_code, currency, 'USD')) "
                                 "WHEN 'USD' THEN %s WHEN 'GBP' THEN %s WHEN 'EUR' THEN %s "
                                 "WHEN 'TRY' THEN %s ELSE %s END")
                    rate_args = [rates.get("USD", 1.0), rates.get("GBP", 1.27),
                                 rates.get("EUR", 1.08), rates.get("TRY", 0.031), 1.0]
                    if gpt_filters.get("min_price") is not None:
                        query += f" AND ({case_expr}) >= %s"
                        params.extend(rate_args + [currency_svc.to_usd(gpt_filters["min_price"], qcur)])
                    if gpt_filters.get("max_price") is not None:
                        query += f" AND ({case_expr}) <= %s"
                        params.extend(rate_args + [currency_svc.to_usd(gpt_filters["max_price"], qcur)])
            else:
                # no AI (or extraction failed) -> keyword fallback
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
            query += " AND (city = %s OR district = %s)"
            params.extend([city.strip(), city.strip()])
        if district and district.strip() and district != "all":
            query += " AND (district = %s OR city = %s OR location ILIKE %s)"
            params.extend([district.strip(), district.strip(), f"%{district.strip()}%"])

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

        # 13. SIRALAMA — AI semantic ordering tek sorguya gömülü (Stage 4).
        # Serbest metin sorgusu varsa, AI açıksa ve kullanıcı açık bir sıralama
        # (fiyat/eski) seçmediyse, ana sorgu doğrudan vektör benzerliğine göre
        # sıralar (ayrı bir rerank round-trip'i YOK). Aksi halde normal sıralama.
        _sort_str = str(sort or "").strip().lower()
        _explicit_sort = any(k in _sort_str for k in
                             ["high", "low", "yüksek", "düşük", "old", "eski"])
        _qvec = openai_client.embed_query(q.strip()) \
            if (q and q.strip() and ai_config.ai_enabled() and not _explicit_sort) else None

        if _qvec is not None:
            # Hibrit sıralama: vektör benzerliği BASKIN + lexical/rating/recency
            # nüansları (ağırlıklar ai_config'te). NULL embedding'ler NULLS LAST.
            order_sql, order_params = query_pipeline.build_hybrid_order_sql(
                openai_client.to_vector_literal(_qvec), q.strip())
            query += order_sql
            params.extend(order_params)
        elif "high to low" in _sort_str or "yüksek" in _sort_str:
            query += " ORDER BY COALESCE(price_normalized, 0) DESC, id DESC"
        elif "low to high" in _sort_str or "düşük" in _sort_str:
            query += " ORDER BY COALESCE(price_normalized, 0) ASC, id DESC"
        elif "oldest" in _sort_str or "eski" in _sort_str or "old" in _sort_str:
            query += " ORDER BY id ASC"
        else:
            query += " ORDER BY id DESC"

        cur.execute(query, tuple(params))
        all_filtered_rows = cur.fetchall()

        # Relevance floor: for a PURELY semantic search (free text, no UI dropdown
        # filters and no GPT-extracted hard filters), drop everything when even the
        # nearest match is too far — so off-topic queries ("castle") return empty
        # instead of nearest-neighbor junk. With any concrete filter set, we skip the
        # gate and honor the filters.
        _ui_filters_present = any([
            listing_type and str(listing_type).strip().lower() not in ("", "all", "mix"),
            property_type and property_type != "all",
            min_price is not None, max_price is not None,
            currency and currency != "all",
            room_count and room_count != "all", bath_count and bath_count != "all",
            min_net_m2 is not None, max_net_m2 is not None,
            min_gross_m2 is not None, max_gross_m2 is not None,
            min_open_m2 is not None, max_open_m2 is not None,
            building_age and building_age != "all", heating and heating != "all",
            country and country != "all", city and city != "all", district and district != "all",
            is_site, credit, swap, property_status, title_type, furniture, otopark, features,
        ])
        _gpt_hard = bool(gpt_filters) and query_pipeline.has_hard_filters(gpt_filters)
        if (_qvec is not None and all_filtered_rows
                and not _ui_filters_present and not _gpt_hard
                and query_pipeline.is_off_topic(q.strip(), False)):
            all_filtered_rows = []

        # Stage 5: LLM precision rerank of the top hits, only when semantic ordering
        # was used (free-text query + AI on + no explicit sort). Self-gates on config.
        if _qvec is not None:
            all_filtered_rows = query_pipeline.llm_rerank_rows(q.strip(), all_filtered_rows)
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

    # --- SEARCH LOGGING (feeds failed-search Pareto / fishbone analysis) ---
    try:
        query_pipeline.log_search(
            q or "", active_filters, total_items,
            user_obj.get("id") if user_obj else None,
        )
    except Exception as _log_err:
        print(f"search log skipped: {_log_err}")

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