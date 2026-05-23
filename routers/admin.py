from fastapi import APIRouter, Request, status, HTTPException, Form, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import database as db
import psycopg2
from psycopg2.extras import RealDictCursor
import os
import time
import shutil
from datetime import datetime
from decimal import Decimal
import math
from typing import List, Optional

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="templates")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Neon DB connection URL (Safely retrieved from environment variables)
DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    """Helper function providing connection to the Neon DB database"""
    conn = psycopg2.connect(DATABASE_URL)
    return conn

# SECURITY BARRIER: Helper function to prevent non-admin access
def verify_admin():
    return getattr(db, "current_user_role", "user") == "admin"


# =========================================================
# 1. LIST ALL SYSTEM PROPERTIES PAGE (GET)
# =========================================================
@router.get("/all-properties", response_class=HTMLResponse)
async def admin_all_properties(request: Request):
    """Page where the admin can view all listings in the system"""
    if not verify_admin():
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    email = getattr(db, "current_user_email", None)
    user_data = db.get_user_from_db(email) if email else {}
    if not user_data:
        user_data = getattr(db, "current_user_data", {})
    
    # Fetch all listings (JOIN injection for the development phase will be resolved in the db layer)
    
    # Checked and assigned new db function to handle agent name and currency formatting in UI
    if hasattr(db, 'get_all_properties_with_agents_from_db'):
        all_props_raw = db.get_all_properties_with_agents_from_db()
    elif hasattr(db, 'get_properties_from_db'):
        # UPDATE: include_passive=True parameter is sent to comply with db/properties.py architecture
        # so that passive listings can also be listed under the 'Passive' tab in the admin panel.
        all_props_raw = db.get_properties_from_db(include_passive=True)
    else:
        all_props_raw = []
    
    # NEW LOGIC UPDATE: 
    # Newly added listings awaiting approval (status = 'approving') are not listed on this page.
    # The buttons here are only intended to switch passive listings to active (or vice versa).
    all_props = []
    for p in all_props_raw:
        if p.get('status') != 'approving':
            # Secure mapping to fill the 'agent_name' structure on the HTML side from relational agent data
            # incoming from the Neon DB schema, ensuring it does not display 'Not Specified' in the interface.
            if 'agent_first_name' in p and p['agent_first_name']:
                p['agent_name'] = f"{p['agent_first_name']} {p.get('agent_last_name', '')}"
            elif 'agent_name' in p and p['agent_name']:
                # Full protection for concatenated (first_name + last_name) fields inside db_admin.py
                pass
            
            # Interface Price Assurance: normalized field is mapped so that HTML templates can directly find price
            if 'price_normalized' in p and not p.get('price'):
                p['price'] = p['price_normalized']
            if 'monthly_price' in p and not p.get('price'):
                p['price'] = p['monthly_price']

            # CURRENCY SYMBOL FIX FROM currency_code OR currency
            currency_raw = str(p.get("currency_code") or p.get("currency") or "").upper()
            if "GBP" in currency_raw or "£" in currency_raw:
                p["currency_symbol"] = "£"
            elif "USD" in currency_raw or "$" in currency_raw:
                p["currency_symbol"] = "$"
            elif "EUR" in currency_raw or "€" in currency_raw:
                p["currency_symbol"] = "€"
            else:
                p["currency_symbol"] = "₺"
                
            all_props.append(p)
    
    # Fully synchronized with the {% for property in all_properties %} loop inside all_properties.html
    return templates.TemplateResponse(request, "all_properties.html", {
        "role": db.current_user_role, 
        "is_admin": True, 
        "p_page": "all-properties",
        "first_name": user_data.get("first_name", ""), 
        "last_name": user_data.get("last_name", ""),
        "profile_image": user_data.get("profile_image", "default_user.png"),
        "all_properties": all_props
    })


# =========================================================
# 2. USERS PAGE (GET)
# =========================================================
@router.get("/users", response_class=HTMLResponse)
async def admin_users(request: Request):
    if not verify_admin():
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    email = getattr(db, "current_user_email", None)
    user_data = db.get_user_from_db(email) if email else {}
    if not user_data:
        user_data = getattr(db, "current_user_data", {})

    # Fetch users from DB to list them in the view
    users_list = []
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, first_name, last_name, email, role, created_at, profile_image FROM users ORDER BY id DESC")
        users_list = cur.fetchall()
    except Exception as e:
        print(f"Users fetch error: {e}")
    finally:
        if cur: cur.close()
        if conn: conn.close()

    return templates.TemplateResponse(request, "users.html", {
        "role": db.current_user_role, 
        "is_admin": True, 
        "p_page": "users",
        "first_name": user_data.get("first_name", ""), 
        "last_name": user_data.get("last_name", ""),
        "profile_image": user_data.get("profile_image", "default_user.png"),
        "users": users_list
    })


# =========================================================
# 3. LIST PROPERTIES AWAITING APPROVAL (GET) - NEON DB INTEGRATED & PAGINATED (6 CARDS PER PAGE)
# =========================================================
@router.get("/approvals", response_class=HTMLResponse)
@router.get("/approving", response_class=HTMLResponse)
async def admin_approving(request: Request):
    """Page listing properties awaiting approval (fully compatible with Neon DB formatting logic and profile data)"""
    if not verify_admin():
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    email = getattr(db, "current_user_email", None)
    user_data = db.get_user_from_db(email) if email else {}
    if not user_data:
        user_data = getattr(db, "current_user_data", {})
    
    # Handle pagination parameter from query string
    params = request.query_params
    try:
        current_page = int(params.get("page", 1))
        if current_page < 1:
            current_page = 1
    except ValueError:
        current_page = 1

    cards_per_page = 6
    properties = []
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        current_cursor_factory = RealDictCursor
        cur = conn.cursor(cursor_factory=current_cursor_factory)

        query = """
            SELECT
                p.id,
                p.name,
                p.location,
                p.monthly_price,
                p.image,
                p.listing_type,
                p.currency,
                p.currency_code,
                p.created_at,
                p.room_count,
                p.net_m2,
                p.status,
                p.agent_id,
                COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '') as agent_name
            FROM properties p
            LEFT JOIN users u ON p.agent_id = u.id
            WHERE LOWER(TRIM(p.status)) = 'approving'
            ORDER BY p.id DESC
        """
        cur.execute(query)
        rows = cur.fetchall()

        # rows tüm elemanları çektiği için len(rows) bize veritabanındaki GERÇEK TOPLAM onay bekleyen sayısını verir (Örn: 7)
        total_count = len(rows)
        print("PENDING APPROVALS TOTAL COUNT:", total_count)

        # Calculate pagination limits
        total_pages = math.ceil(total_count / cards_per_page) if total_count > 0 else 1
        if current_page > total_pages:
            current_page = total_pages

        start_idx = (current_page - 1) * cards_per_page
        end_idx = start_idx + cards_per_page
        
        # Sayfaya sadece limit kadar ilan ayrıştırılıyor (Örn: 6 adet)
        paginated_rows = rows[start_idx:end_idx]

        for item in paginated_rows:
            prop = dict(item)

            # TITLE MAPPING
            prop["title"] = prop.get("name") or "Unnamed Listing"

            # IMAGE PATH ADJUSTMENT
            image_path = prop.get("image")
            if image_path:
                image_path = str(image_path).strip().replace("\\", "/")
            else:
                image_path = None
            prop["image"] = image_path

            # LISTING TYPE CONVERSION (listing_type -> display_type)
            listing_type = str(prop.get("listing_type") or "").lower()
            if "rent" in listing_type:
                prop["display_type"] = "FOR RENT"
            else:
                prop["display_type"] = "FOR SALE"

            # RESPONSIBLE AGENT NAME CHECK
            agent_name = str(prop.get("agent_name") or "").strip()
            if agent_name == "":
                prop["agent_name"] = f"Agent #{prop.get('agent_id')}"
            else:
                prop["agent_name"] = agent_name

            # CURRENCY SYMBOL FIX FROM currency_code OR currency
            currency_raw = str(prop.get("currency_code") or prop.get("currency") or "").upper()
            if "GBP" in currency_raw or "£" in currency_raw:
                prop["currency_symbol"] = "£"
            elif "USD" in currency_raw or "$" in currency_raw:
                prop["currency_symbol"] = "$"
            elif "EUR" in currency_raw or "€" in currency_raw:
                prop["currency_symbol"] = "€"
            else:
                prop["currency_symbol"] = "₺"

            # PRICE FORMATTING (monthly_price -> formatted_price)
            price = prop.get("monthly_price")
            if price is not None:
                try:
                    prop["formatted_price"] = f"{float(price):,.0f}"
                except:
                    prop["formatted_price"] = str(price)
            else:
                prop["formatted_price"] = "—"

            # DATE FORMATTING (created_at)
            created_at = prop.get("created_at")
            if isinstance(created_at, datetime):
                prop["created_at"] = created_at.strftime("%d.%m.%Y")
            else:
                prop["created_at"] = "New Application"

            # SQUARE METERS FIELD (net_m2 -> square_meters)
            prop["square_meters"] = prop.get("net_m2") or "—"

            # UI price assurance fallback mapping
            if 'price_normalized' in prop and not prop.get('price'):
                prop['price'] = prop['price_normalized']
            if 'monthly_price' in prop and not prop.get('price'):
                prop['price'] = prop['monthly_price']

            properties.append(prop)

    except Exception as e:
        print("APPROVAL LIST ERROR IN ADMIN.PY:", e)
        total_pages = 1
        total_count = 0
    finally:
        if cur: cur.close()
        if conn: conn.close()

    return templates.TemplateResponse(request, "approving.html", {
        "role": db.current_user_role, 
        "is_admin": True, 
        "p_page": "approving",
        "first_name": user_data.get("first_name", ""), 
        "last_name": user_data.get("last_name", ""),
        "profile_image": user_data.get("profile_image", "default_user.png"),
        "properties": properties,
        "pending_properties": properties, # HTML şablonuna filtrelenmiş 6'lı ilan listesi gider
        "current_page": current_page,
        "total_pages": total_pages,
        "total_count": total_count,      # HTML şablonuna kısıtlanmamış gerçek toplam sayı gider (Örn: 7)
        "has_next": current_page < total_pages,
        "has_prev": current_page > 1
    })


# =========================================================
# 4. DASHBOARD PAGE (GET)
# =========================================================
@router.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    if not verify_admin():
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    email = getattr(db, "current_user_email", None)
    user_data = db.get_user_from_db(email) if email else {}
    if not user_data:
        user_data = getattr(db, "current_user_data", {})
        
    # Fetch real counts from DB for dashboard summary
    stats = {"total_properties": 0, "pending_approvals": 0, "total_users": 0}
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM properties")
        stats["total_properties"] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM properties WHERE LOWER(TRIM(status)) = 'approving'")
        stats["pending_approvals"] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM users")
        stats["total_users"] = cur.fetchone()[0]
    except Exception as e:
        print(f"Dashboard statistics gather error: {e}")
    finally:
        if cur: cur.close()
        if conn: conn.close()

    return templates.TemplateResponse(request, "dashboard.html", {
        "role": db.current_user_role, 
        "is_admin": True, 
        "p_page": "dashboard",
        "first_name": user_data.get("first_name", ""), 
        "last_name": user_data.get("last_name", ""),
        "profile_image": user_data.get("profile_image", "default_user.png"),
        "stats": stats
    })


# =========================================================
# 5. SYSTEM LOGS PAGE (GET)
# =========================================================
@router.get("/system-logs", response_class=HTMLResponse)
async def admin_system_logs(request: Request):
    if not verify_admin():
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    email = getattr(db, "current_user_email", None)
    user_data = db.get_user_from_db(email) if email else {}
    if not user_data:
        user_data = getattr(db, "current_user_data", {})
        
    logs = get_system_logs_from_db()

    return templates.TemplateResponse(request, "system_logs.html", {
        "role": db.current_user_role, 
        "is_admin": True, 
        "p_page": "system-logs",
        "first_name": user_data.get("first_name", ""), 
        "last_name": user_data.get("last_name", ""),
        "profile_image": user_data.get("profile_image", "default_user.png"),
        "logs": logs
    })


# =========================================================
# 6. SALES LOGS PAGE (GET)
# =========================================================
@router.get("/sales-logs", response_class=HTMLResponse)
async def admin_sales_logs(request: Request):
    if not verify_admin():
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    email = getattr(db, "current_user_email", None)
    user_data = db.get_user_from_db(email) if email else {}
    if not user_data:
        user_data = getattr(db, "current_user_data", {})
        
    sales = get_sales_logs_from_db()

    return templates.TemplateResponse(request, "sales_logs.html", {
        "role": db.current_user_role, 
        "is_admin": True, 
        "p_page": "sales-logs",
        "first_name": user_data.get("first_name", ""), 
        "last_name": user_data.get("last_name", ""),
        "profile_image": user_data.get("profile_image", "default_user.png"),
        "sales": sales
    })


# =========================================================
# 7. DELETE / DEACTIVATE PROPERTY ENDPOINT (POST)
# =========================================================
@router.post("/delete-property/{property_id}")
async def admin_delete_property_endpoint(property_id: str):
    """
    Yönetici panelinden (all-properties veya approving) gelen silme/pasife alma isteği.
    İlanın durumunu doğrudan 'passive' moduna çeker.
    """
    if not verify_admin():
        return JSONResponse(status_code=403, content={"success": False, "error": "Unauthorized Access"})
    
    conn = None
    cur = None
    try:
        clean_id = int(property_id) if str(property_id).isdigit() else property_id
        success = False

        # 1. Öncelik: Tanımlı ise veritabanı katmanı (db) fonksiyonlarını kullan
        if hasattr(db, 'delete_property_from_db'):
            success = db.delete_property_from_db(clean_id)
        elif hasattr(db, 'soft_delete_property_in_db'):
            success = db.soft_delete_property_in_db(clean_id)
        elif hasattr(db, 'update_property_status'):
            success = db.update_property_status(clean_id, "passive")
        elif hasattr(db, 'update_property_in_db'):
            success = db.update_property_in_db(clean_id, {"status": "passive"})
        else:
            # 2. Öncelik (Yedek): Fonksiyonlar yoksa doğrudan SQL ile veritabanını güncelle
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("UPDATE properties SET status = 'passive' WHERE id = %s", (clean_id,))
            conn.commit()
            success = cur.rowcount > 0
            
        if success:
            return {"success": True, "message": "Property successfully changed to passive mode."}
        else:
            return JSONResponse(status_code=400, content={"success": False, "error": "Property status could not be updated."})
            
    except Exception as e:
        if conn: conn.rollback()
        print(f"Admin delete property backend error: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": f"Server error: {str(e)}"})
    finally:
        if cur: cur.close()
        if conn: conn.close()


# =========================================================
# 8. UPDATE PROPERTY STATUS ENDPOINT (POST)
# =========================================================
@router.post("/update-property/{property_id}")
async def admin_update_property_status_endpoint(property_id: str, request: Request):
    """
    Genel yönetim arayüzünden gelen durum güncelleme isteği.
    Form verisinden (veya URLSearchParams) gelen 'status' değerine göre ilanı günceller.
    """
    if not verify_admin():
        return JSONResponse(status_code=403, content={"success": False, "error": "Unauthorized Access"})
        
    conn = None
    cur = None
    try:
        clean_id = int(property_id) if str(property_id).isdigit() else property_id
        form_data = await request.form()
        target_status = form_data.get("status", "active")
        success = False

        # 1. Öncelik: Tanımlı ise veritabanı katmanı (db) fonksiyonlarını kullan
        if hasattr(db, 'update_property_status'):
            success = db.update_property_status(clean_id, target_status)
        elif hasattr(db, 'update_property_in_db'):
            success = db.update_property_in_db(clean_id, {"status": target_status})
        else:
            # 2. Öncelik (Yedek): Doğrudan SQL ile veritabanını güncelle
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("UPDATE properties SET status = %s WHERE id = %s", (target_status, clean_id))
            conn.commit()
            success = cur.rowcount > 0
            
        if success:
            return {"success": True, "message": f"Property status successfully updated to {target_status}."}
        else:
            return JSONResponse(status_code=400, content={"success": False, "error": "Database update error."})
            
    except Exception as e:
        if conn: conn.rollback()
        print(f"Admin update property status backend error: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": f"Server error: {str(e)}"})
    finally:
        if cur: cur.close()
        if conn: conn.close()


# =========================================================
# 9. QUICK APPROVE PROPERTY (POST) - İlanı Doğrudan Aktif Yapar
# =========================================================
@router.post("/approve-property/{property_id}")
async def admin_quick_approve_property(property_id: int):
    """Approving sayfasındaki butonlar için hızlı onaylama (status -> 'active') endpoint'i"""
    if not verify_admin():
        return JSONResponse(status_code=403, content={"success": False, "message": "Yetkisiz erişim: Admin değilsiniz."})
    
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE properties SET status = 'active' WHERE id = %s",
            (property_id,)
        )
        conn.commit()
        
        if cur.rowcount == 0:
            return JSONResponse(status_code=404, content={"success": False, "message": "İlan bulunamadı."})
            
        return {"success": True, "message": "Property approved successfully."}
        
    except Exception as e:
        if conn: conn.rollback()
        print(f"Quick approve backend error: {e}")
        return JSONResponse(status_code=500, content={"success": False, "message": f"Veritabanı hatası: {str(e)}"})
    finally:
        if cur: cur.close()
        if conn: conn.close()


# =========================================================
# 10. QUICK REJECT PROPERTY (POST) - İlanı Doğrudan Pasif Yapar
# =========================================================
@router.post("/reject-property/{property_id}")
async def admin_quick_reject_property(property_id: int):
    """Approving sayfasındaki butonlar için hızlı reddetme (status -> 'passive') endpoint'i"""
    if not verify_admin():
        return JSONResponse(status_code=403, content={"success": False, "message": "Yetkisiz erişim: Admin değilsiniz."})
    
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE properties SET status = 'passive' WHERE id = %s",
            (property_id,)
        )
        conn.commit()
        
        if cur.rowcount == 0:
            return JSONResponse(status_code=404, content={"success": False, "message": "İlan bulunamadı."})
            
        return {"success": True, "message": "Property rejected successfully."}
        
    except Exception as e:
        if conn: conn.rollback()
        print(f"Quick reject backend error: {e}")
        return JSONResponse(status_code=500, content={"success": False, "message": f"Veritabanı hatası: {str(e)}"})
    finally:
        if cur: cur.close()
        if conn: conn.close()


# =========================================================
# 9. SINGLE PROPERTY DATA FOR MODAL ENDPOINT (GET)
#    CRITICAL UPDATE: 'features' alanı JavaScript input_features uyumluluğu için virgülle ayrılmış stringe çevrildi!
# =========================================================
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


# =========================================================
# 10. UPDATE PROPERTY FROM MODAL API ENDPOINT (POST)
#     EKSİKSİZ YAPILANDIRMA: Form veri akışını, özellikleri ve resimleri ilişkili tablolara kaydeder.
# =========================================================
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


# =========================================================
# INTERNAL POOLS: BACKEND CONTROL EXTENSIONS (STABLE)
# =========================================================
def get_pending_approvals_from_db():
    """Approving ilanlar listesi için iç fonksiyon"""
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM properties WHERE LOWER(TRIM(status)) = 'approving' ORDER BY id DESC")
        return cur.fetchall() or []
    except Exception as e:
        print(f"Pending lists internal fetch error: {e}")
        return []
    finally:
        if cur: cur.close()
        if conn: conn.close()

def get_system_logs_from_db():
    """Fetches system operational configuration database parameters as logs"""
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT current_database() as db_name, version() as system_version, now() as timestamp")
        return cur.fetchall() or []
    except Exception as e:
        print(f"System configuration logger error: {e}")
        return []
    finally:
        if cur: cur.close()
        if conn: conn.close()

def get_sales_logs_from_db():
    """Fetches logs for properties that are currently finalized or actively online"""
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, name, monthly_price, currency_code, status, created_at FROM properties WHERE LOWER(TRIM(status)) = 'active' ORDER BY id DESC LIMIT 50")
        return cur.fetchall() or []
    except Exception as e:
        print(f"Sales compiler background evaluation exception: {e}")
        return []
    finally:
        if cur: cur.close()
        if conn: conn.close()