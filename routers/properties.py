import os
import time
import shutil
import pytz
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from psycopg2.extras import RealDictCursor

import database as db  # Veritabanı bağlantısı katmanı

router = APIRouter()
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

@router.post("/add-property")
async def add_property(request: Request):
    user_id_cookie = request.cookies.get("user_id")
    user_data = db.get_user_from_cookie(user_id_cookie) if user_id_cookie else None
    user_role = user_data.get("role") if user_data else "guest"
    
    if not user_data or user_role != 'agent':
        return JSONResponse(status_code=401, content={"error": "İlan vermek için Agent hesabı ile giriş yapmalısınız."})

    form_data = await request.form()
    
    name = form_data.get("name", "").strip()
    location = form_data.get("location", "").strip()
    monthly_price = float(form_data.get("monthly_price") or 0.0)
    currency_code = form_data.get("currency_code", "TRY")
    listing_type = form_data.get("listing_type", "sale")
    property_type = form_data.get("property_type", "Villa")
    
    gross_m2 = int(form_data.get("gross_m2") or 0)
    net_m2 = int(form_data.get("net_m2") or 0)
    open_m2 = int(form_data.get("open_m2") or 0)
    room_count = str(form_data.get("room_count") or "0").strip()
    
    beds = int(form_data.get("beds") or 0)
    baths = int(form_data.get("baths") or 0)
    guests = int(form_data.get("guests") or 0)
    dues = float(form_data.get("dues") or 0.0)
    
    building_age = form_data.get("building_age", "-").strip()
    heating = form_data.get("heating", "-").strip()
    deed_status = form_data.get("deed_status", "-").strip()
    
    is_site = form_data.get("is_site", "Hayır")
    site_name = form_data.get("site_name", "-")
    is_credit = form_data.get("is_credit", "Hayır")
    is_trade = form_data.get("is_trade", "Hayır")
    description = form_data.get("description", "").strip() or None

    features_raw = form_data.getlist("features")
    selected_features_ids = [int(f) for f in features_raw if str(f).isdigit()]

    upload_folder = os.path.join(BASE_DIR, "static/htmlfotos")
    if not os.path.exists(upload_folder):
        os.makedirs(upload_folder)

    image_urls_list = []
    saved_disk_paths = []

    # Kapak Resmi İşleme (single_cover)
    cover_file = form_data.get("single_cover")
    if cover_file and hasattr(cover_file, "filename") and cover_file.filename:
        file_extension = os.path.splitext(cover_file.filename)[1].lower()
        if file_extension in ['.png', '.jpg', '.jpeg', '.webp']:
            new_filename = f"prop_{int(time.time())}_cover{file_extension}"
            file_path = os.path.join(upload_folder, new_filename)
            try:
                with open(file_path, "wb") as buffer:
                    shutil.copyfileobj(cover_file.file, buffer)
                image_urls_list.append(f"htmlfotos/{new_filename}")
                saved_disk_paths.append(file_path)
            except Exception as e:
                print(f"Kapak fotoğrafı kaydetme hatası: {e}")

    # Çoklu Galeri Resimleri İşleme (main_image)
    uploaded_files = form_data.getlist("main_image")
    for idx, file_item in enumerate(uploaded_files):
        if hasattr(file_item, "filename") and file_item.filename:
            file_extension = os.path.splitext(file_item.filename)[1].lower()
            if file_extension in ['.png', '.jpg', '.jpeg', '.webp']:
                new_filename = f"prop_{int(time.time())}_{idx}{file_extension}"
                file_path = os.path.join(upload_folder, new_filename)
                try:
                    with open(file_path, "wb") as buffer:
                        shutil.copyfileobj(file_item.file, buffer)
                    image_urls_list.append(f"htmlfotos/{new_filename}")
                    saved_disk_paths.append(file_path)
                except Exception as e:
                    print(f"Çoklu dosya kaydetme hatası ({idx}): {e}")

    if not image_urls_list:
        image_urls_list.append("htmlfotos/placeholder.jpg")

    loc_parts = [p.strip() for p in location.split(',')]
    district = loc_parts[0] if len(loc_parts) > 0 else ""
    city = loc_parts[1] if len(loc_parts) > 1 else ""
    country = loc_parts[2] if len(loc_parts) > 2 else ""

    clean_is_site = is_site if is_site in ["Evet", "Hayır"] else "Hayır"
    clean_site_name = site_name if clean_is_site == "Evet" and site_name else "-"

    if listing_type == "sale":
        clean_is_credit = is_credit if is_credit in ["Evet", "Hayır"] else "Hayır"
        clean_is_trade = is_trade if is_trade in ["Evet", "Hayır"] else "Hayır"
    else:
        clean_is_credit = "Hayır"
        clean_is_trade = "Hayır"

    property_data = {
        "name": name, "title": name, "location": location,
        "district": district, "city": city, "country": country,
        "monthly_price": monthly_price, "price": monthly_price, "price_normalized": monthly_price,
        "listing_type": listing_type, "type": listing_type, "property_type": property_type,
        "gross_m2": gross_m2, "net_m2": net_m2, "open_m2": open_m2, "room_count": room_count,
        "beds": beds, "baths": baths, "guests": guests, "dues": dues,
        "building_age": building_age, "heating": heating, "is_site": clean_is_site,
        "site_name": clean_site_name, "is_credit": clean_is_credit, "is_trade": clean_is_trade,
        "currency_code": currency_code, "currency": currency_code, "deed_status": deed_status,
        "description": description, "image": image_urls_list[0], "status": "approving"
    }

    agent_id = user_data.get('id')
    clean_agent_id = int(agent_id) if str(agent_id).isdigit() else agent_id
   
    try:
        success = db.add_full_property_to_db(
            agent_id=clean_agent_id, 
            data=property_data, 
            image_urls=image_urls_list, 
            selected_features=selected_features_ids
        )
    except Exception as e:
        print(f"Veritabanı ekleme fonksiyonu hatası: {e}")
        success = False

    if success:
        return RedirectResponse(url="/profile/properties", status_code=303)
    else:
        for path in saved_disk_paths:
            if os.path.exists(path): os.remove(path)
        return JSONResponse(status_code=500, content={"error": "Veritabanı kaydı sırasında bir hata oluştu."})

@router.get("/api/features")
async def get_features():
    try:
        return db.get_all_features_from_db()
    except Exception as e:
        print(f"API Hatası (Features): {e}")
        return []

@router.get("/api/property/{property_id}")
async def get_single_property_api(property_id: str):
    try:
        clean_id = int(property_id) if str(property_id).isdigit() else property_id
        prop = None
        
        if hasattr(db, 'get_property_by_id_from_db'): prop = db.get_property_by_id_from_db(clean_id)
        elif hasattr(db, 'get_property_from_db'): prop = db.get_property_from_db(clean_id)
        elif hasattr(db, 'get_property_by_id'): prop = db.get_property_by_id(clean_id)
        else:
            all_props = db.get_properties_from_db(include_passive=True) if hasattr(db, 'get_properties_from_db') else []
            prop = next((p for p in all_props if str(p.get('id')) == str(clean_id)), None)
            
        if prop:
            safe_prop = {}
            for key, value in dict(prop).items():
                if isinstance(value, Decimal): safe_prop[key] = float(value)
                elif isinstance(value, datetime): safe_prop[key] = value.isoformat()
                elif isinstance(value, list): safe_prop[key] = value
                elif value is None:
                    if key in ['price', 'price_normalized', 'dues', 'monthly_price', 'gross_m2', 'net_m2', 'beds', 'baths', 'guests', 'open_m2']:
                        safe_prop[key] = 0
                    elif key in ['is_site', 'is_credit', 'is_trade']: safe_prop[key] = "Hayır"
                    else: safe_prop[key] = ""
                else: safe_prop[key] = value

            if 'name' in safe_prop and not safe_prop.get('title'): safe_prop['title'] = safe_prop['name']
            if 'title' in safe_prop and not safe_prop.get('name'): safe_prop['name'] = safe_prop['title']
            if 'price_normalized' in safe_prop and not safe_prop.get('price'): safe_prop['price'] = safe_prop['price_normalized']
            if 'price' in safe_prop and not safe_prop.get('price_normalized'): safe_prop['price_normalized'] = safe_prop['price']
            if 'currency' in safe_prop and not safe_prop.get('currency_code'): safe_prop['currency_code'] = safe_prop['currency']
            if 'currency_code' in safe_prop and not safe_prop.get('currency'): safe_prop['currency'] = safe_prop['currency_code']
            if 'listing_type' in safe_prop and not safe_prop.get('type'): safe_prop['type'] = safe_prop['listing_type']
            if 'type' in safe_prop and not safe_prop.get('listing_type'): safe_prop['listing_type'] = safe_prop['type']

            return JSONResponse(content=safe_prop)
        return JSONResponse(status_code=404, content={"error": "İlan bulunamadı."})
    except Exception as e:
        print(f"Kritik /api/property/{property_id} Çökme Detayı: {str(e)}")
        return JSONResponse(status_code=500, content={"error": f"Veri okuma hatası: {str(e)}"})

@router.post("/api/property/update/{property_id}")
async def update_property_endpoint(property_id: str, request: Request):
    try:
        form_data = await request.form()
        update_data = {}

        if "name" in form_data:
            title_val = form_data.get("name", "").strip()
            update_data["name"] = title_val
            update_data["title"] = title_val

        if "location" in form_data: update_data["location"] = form_data.get("location")
        if "description" in form_data: update_data["description"] = form_data.get("description")
        if "status" in form_data: update_data["status"] = form_data.get("status")
       
        if "currency_code" in form_data:
            curr = form_data.get("currency_code")
            update_data["currency"] = curr
            update_data["currency_code"] = curr
            
        if "deed_status" in form_data: update_data["deed_status"] = form_data.get("deed_status")
        if "site_name" in form_data: update_data["site_name"] = form_data.get("site_name")
       
        if "listing_type" in form_data:
            l_type = form_data.get("listing_type")
            update_data["type"] = l_type
            update_data["listing_type"] = l_type
            
        if "is_site" in form_data: update_data["is_site"] = form_data.get("is_site")
        if "is_credit" in form_data: update_data["is_credit"] = form_data.get("is_credit")
        if "is_trade" in form_data: update_data["is_trade"] = form_data.get("is_trade")

        if "monthly_price" in form_data and form_data.get("monthly_price") != "":
            price_val = float(form_data.get("monthly_price") or 0.0)
            update_data["monthly_price"] = price_val
            update_data["price"] = price_val
            update_data["price_normalized"] = price_val

        if "room_count" in form_data: update_data["room_count"] = str(form_data.get("room_count") or "0")
        if "beds" in form_data and form_data.get("beds") != "": update_data["beds"] = int(form_data.get("beds") or 0)
        if "baths" in form_data and form_data.get("baths") != "": update_data["baths"] = int(form_data.get("baths") or 0)
            
        if "gross_m2" in form_data and form_data.get("gross_m2") != "": update_data["gross_m2"] = int(form_data.get("gross_m2") or 0)
        if "net_m2" in form_data and form_data.get("net_m2") != "": update_data["net_m2"] = int(form_data.get("net_m2") or 0)
        if "open_m2" in form_data and form_data.get("open_m2") != "": update_data["open_m2"] = int(form_data.get("open_m2") or 0)
        if "guests" in form_data and form_data.get("guests") != "": update_data["guests"] = int(form_data.get("guests") or 0)
        if "dues" in form_data and form_data.get("dues") != "": update_data["dues"] = float(form_data.get("dues") or 0.0)

        if "property_type" in form_data: update_data["property_type"] = form_data.get("property_type")
        if "building_age" in form_data: update_data["building_age"] = form_data.get("building_age")
        if "heating" in form_data: update_data["heating"] = form_data.get("heating")

        features_list = form_data.getlist("features")
        if features_list: update_data["features"] = [int(f) for f in features_list if str(f).isdigit()]

        if "location" in update_data and update_data["location"]:
            loc_parts = [p.strip() for p in update_data["location"].split(',')]
            update_data["district"] = loc_parts[0] if len(loc_parts) > 0 else ""
            update_data["city"] = loc_parts[1] if len(loc_parts) > 1 else ""
            update_data["country"] = loc_parts[2] if len(loc_parts) > 2 else ""

        # Fotoğraf Güncelleme
        upload_folder = os.path.join(BASE_DIR, "static/htmlfotos")
        if not os.path.exists(upload_folder): os.makedirs(upload_folder)
        new_image_urls = []
        
        cover_file = form_data.get("single_cover")
        if cover_file and hasattr(cover_file, "filename") and cover_file.filename:
            file_extension = os.path.splitext(cover_file.filename)[1].lower()
            if file_extension in ['.png', '.jpg', '.jpeg', '.webp']:
                new_filename = f"prop_{int(time.time())}_update_cover{file_extension}"
                file_path = os.path.join(upload_folder, new_filename)
                try:
                    with open(file_path, "wb") as buffer: shutil.copyfileobj(cover_file.file, buffer)
                    cover_url = f"htmlfotos/{new_filename}"
                    update_data["image"] = cover_url
                    new_image_urls.append(cover_url)
                except Exception as e: print(f"Güncellemede kapak fotoğrafı kaydetme hatası: {e}")

        uploaded_files = form_data.getlist("main_image")
        for idx, file_item in enumerate(uploaded_files):
            if hasattr(file_item, "filename") and file_item.filename:
                file_extension = os.path.splitext(file_item.filename)[1].lower()
                if file_extension in ['.png', '.jpg', '.jpeg', '.webp']:
                    new_filename = f"prop_{int(time.time())}_up_gal_{idx}{file_extension}"
                    file_path = os.path.join(upload_folder, new_filename)
                    try:
                        with open(file_path, "wb") as buffer: shutil.copyfileobj(file_item.file, buffer)
                        new_image_urls.append(f"htmlfotos/{new_filename}")
                    except Exception as e: print(f"Güncellemede galeri fotoğrafı kaydetme hatası ({idx}): {e}")

        if new_image_urls:
            update_data["image_urls"] = new_image_urls
            if "image" not in update_data: update_data["image"] = new_image_urls[0]

        clean_id = int(property_id) if str(property_id).isdigit() else property_id
        user_id_cookie = request.cookies.get("user_id")
        user_data = db.get_user_from_cookie(user_id_cookie) if user_id_cookie else None
        user_role = user_data.get("role") if user_data else "guest"

        success = False
        if hasattr(db, 'update_property_in_db'): success = db.update_property_in_db(clean_id, update_data)
        elif hasattr(db, 'update_property_status') and "status" in update_data and len(update_data) == 1:
            success = db.update_property_status(clean_id, update_data["status"])
        else: success = True

        if success:
            redirect_url = "/admin/all-properties" if user_role == "admin" else "/profile/properties"
            return RedirectResponse(url=redirect_url, status_code=303)
        return JSONResponse(status_code=400, content={"error": "Veritabanı güncelleme hatası."})
            
    except Exception as e:
        print(f"Kritik Güncelleme Hatası Logu: {str(e)}")
        return JSONResponse(status_code=500, content={"error": f"Sunucu hatası: {str(e)}"})