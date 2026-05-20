from fastapi import APIRouter, Request, Form, status, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import database as db
import os
import shutil
import datetime
import pytz  # Zaman dilimi dönüşümleri için eklendi
from typing import Optional

router = APIRouter(prefix="/profile")
templates = Jinja2Templates(directory="templates")

# Zaman dilimi tanımlamaları
utc_tz = pytz.utc
tr_tz = pytz.timezone("Europe/Istanbul")

# --- YARDIMCI FONKSİYONLAR ---
def get_admin_status():
    """Kullanıcının rolü admin ise True döner"""
    # current_user_role değerinin db modülünde tanımlı olduğundan emin olunmalıdır
    return getattr(db, "current_user_role", "user") == "admin"

def get_safe_current_user():
    """Küresel state yönetiminden kullanıcı verilerini güvenli bir şekilde çeker"""
    email = getattr(db, "current_user_email", None)
    if not email:
        return None, {}
    
    user_data = db.get_user_from_db(email)
    if not user_data:
        user_data = getattr(db, "current_user_data", {})
    return email, user_data

# --- GENEL / ORTAK ROTALAR ---

@router.get("/personal-info", response_class=HTMLResponse)
async def personal_info(request: Request):
    """Kişisel Bilgiler Sayfası"""
    user_email, user_data = get_safe_current_user()
    
    if not user_email:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    return templates.TemplateResponse(request, "personal_info.html", {
        "role": getattr(db, "current_user_role", "user"),
        "is_admin": get_admin_status(),
        "first_name": user_data.get("first_name", ""),
        "last_name": user_data.get("last_name", ""),
        "email": user_email,
        "phone": user_data.get("phone", ""),
        "gender": user_data.get("gender", ""),
        "profile_image": user_data.get("profile_image", "default_user.png"),
        "iban": user_data.get("iban", ""),
        "id_no": user_data.get("id_no", ""),
        "company_name": user_data.get("company_name", ""),
        "p_page": "info"
    })

@router.post("/update-info")
async def update_info(
    request: Request, 
    first_name: str = Form(...), 
    last_name: str = Form(...),
    phone: Optional[str] = Form(default=None),
    gender: Optional[str] = Form(default=None),
    iban: Optional[str] = Form(default=None),
    id_no: Optional[str] = Form(default=None),
    company_name: Optional[str] = Form(default=None),
    new_password: Optional[str] = Form(default=None),
    profile_image: Optional[UploadFile] = File(default=None)
):
    """Kişisel Bilgileri ve Profil Fotoğrafını DB içinde günceller"""
    user_email, user_data = get_safe_current_user()
    if not user_email:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
        
    filename = user_data.get("profile_image", "default_user.png")

    if profile_image and profile_image.filename:
        upload_dir = "static/htmlfotos"
        if not os.path.exists(upload_dir):
            os.makedirs(upload_dir)
            
        extension = os.path.splitext(profile_image.filename)[1]
        user_id = user_data.get('id', 'unknown')
        filename = f"user_{user_id}{extension}"
        file_path = os.path.join(upload_dir, filename)
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(profile_image.file, buffer)

    update_data = {
        "first_name": first_name,
        "last_name": last_name,
        "phone": phone,
        "gender": gender,
        "iban": iban,
        "id_no": id_no,
        "company_name": company_name,
        "profile_image": filename
    }
    
    if new_password and new_password.strip() != "":
        update_data["password"] = new_password

    try:
        db.update_user_in_db(user_email, update_data)
        refreshed_user = db.get_user_from_db(user_email)
        if refreshed_user:
            db.current_user_data = refreshed_user
    except Exception as e:
        print(f"Update hatası: {e}")

    return RedirectResponse(url="/profile/personal-info", status_code=status.HTTP_303_SEE_OTHER)

@router.get("/messages", response_class=HTMLResponse)
async def my_messages(request: Request, chat_id: Optional[str] = None):
    """Mesajlar Sayfası (Neon DB Entegrasyonlu Yeni Nesil Chat Sistemi)"""
    
    clean_chat_id = None
    if chat_id and chat_id.strip() and chat_id != "undefined" and chat_id != "None":
        try:
            clean_chat_id = int(chat_id)
        except ValueError:
            clean_chat_id = None

    user_email, user_data = get_safe_current_user()
    if not user_email:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    user_id = user_data.get("id")
    role = getattr(db, "current_user_role", "user")

    conversations = []
    active_chat_partner = None
    active_property = None
    messages = []
    unread_messages_count = 0

    conn = db.get_db_connection()
    if conn:
        try:
            from psycopg2.extras import RealDictCursor
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # 1. Kullanıcının dahil olduğu tüm sohbet odalarını çekiyoruz
            if role == 'admin':
                query = """
                    SELECT cr.id as room_id, cr.id as chat_id, cr.property_id, p.name as property_title,
                           u.id as partner_id, (COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')) as partner_name, u.profile_image as partner_avatar,
                           (SELECT message_text FROM chat_messages WHERE room_id = cr.id ORDER BY created_at DESC LIMIT 1) as last_message,
                           (SELECT created_at FROM chat_messages WHERE room_id = cr.id ORDER BY created_at DESC LIMIT 1) as last_message_time,
                           (SELECT sender_id FROM chat_messages WHERE room_id = cr.id ORDER BY created_at DESC LIMIT 1) as last_message_sender,
                           (SELECT is_read FROM chat_messages WHERE room_id = cr.id ORDER BY created_at DESC LIMIT 1) as last_message_read,
                           0 as unread_count
                    FROM chat_rooms cr
                    LEFT JOIN properties p ON cr.property_id = p.id
                    LEFT JOIN users u ON cr.user_id = u.id
                    WHERE cr.is_ai_chat = FALSE ORDER BY cr.created_at DESC;
                """
                cur.execute(query)
            else:
                query = """
                    SELECT 
                        cr.id as room_id,
                        cr.id as chat_id,
                        cr.property_id,
                        p.name as property_title,
                        (CASE WHEN cr.agent_id = %s THEN u.id ELSE a.id END) as partner_id,
                        (CASE WHEN cr.agent_id = %s THEN (COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')) ELSE (COALESCE(a.first_name, '') || ' ' || COALESCE(a.last_name, '')) END) as partner_name,
                        (CASE WHEN cr.agent_id = %s THEN u.profile_image ELSE a.profile_image END) as partner_avatar,
                        (SELECT message_text FROM chat_messages WHERE room_id = cr.id ORDER BY created_at DESC LIMIT 1) as last_message,
                        (SELECT created_at FROM chat_messages WHERE room_id = cr.id ORDER BY created_at DESC LIMIT 1) as last_message_time,
                        (SELECT sender_id FROM chat_messages WHERE room_id = cr.id ORDER BY created_at DESC LIMIT 1) as last_message_sender,
                        (SELECT is_read FROM chat_messages WHERE room_id = cr.id ORDER BY created_at DESC LIMIT 1) as last_message_read,
                        (SELECT COUNT(*) FROM chat_messages WHERE room_id = cr.id AND sender_id != %s AND is_read = FALSE) as unread_count
                    FROM chat_rooms cr
                    LEFT JOIN properties p ON cr.property_id = p.id
                    LEFT JOIN users u ON cr.user_id = u.id
                    LEFT JOIN users a ON cr.agent_id = a.id
                    WHERE (cr.user_id = %s OR cr.agent_id = %s) AND cr.is_ai_chat = FALSE 
                    ORDER BY cr.created_at DESC;
                """
                cur.execute(query, (user_id, user_id, user_id, user_id, user_id, user_id))

            raw_conversations = cur.fetchall()
            
            for c in raw_conversations:
                p_img = c.get("partner_avatar")
                if not p_img or not str(p_img).strip():
                    p_img = "default_user.png"
                
                # Sol listedeki zaman dönüşümü
                raw_time = c.get("last_message_time")
                if raw_time and hasattr(raw_time, "strftime"):
                    if raw_time.tzinfo is not None:
                        tr_time = raw_time.astimezone(tr_tz)
                    else:
                        tr_time = tr_tz.localize(raw_time) if hasattr(tr_tz, 'localize') else raw_time.replace(tzinfo=tr_tz)
                    time_str = tr_time.strftime("%H:%M")
                else:
                    time_str = ""
                    
                partner_name_str = c.get("partner_name", "").strip()
                
                conversations.append({
                    "id": c["room_id"],
                    "chat_id": c["chat_id"],
                    "room_id": c["room_id"],
                    "property_id": c["property_id"],
                    "property_title": c["property_title"],
                    "partner_id": c.get("partner_id"),
                    "first_name": partner_name_str.split()[0] if partner_name_str else "Kullanıcı",
                    "last_name": " ".join(partner_name_str.split()[1:]) if len(partner_name_str.split()) > 1 else "",
                    "profile_image": p_img,
                    "last_message": c["last_message"] if c["last_message"] else "Henüz mesaj yok.",
                    "last_message_time": time_str,
                    "last_message_sender": c.get("last_message_sender"),
                    "last_message_read": c.get("last_message_read"),
                    "unread_count": int(c["unread_count"]) if c.get("unread_count") else 0,
                    "is_online": True
                })

            unread_messages_count = sum(conversations_item['unread_count'] for conversations_item in conversations)

            # 2. Eğer aktif bir chat odası seçildiyse detay verilerini besle
            if clean_chat_id:
                cur.execute("UPDATE chat_messages SET is_read = TRUE WHERE room_id = %s AND sender_id != %s;", (clean_chat_id, user_id))
                conn.commit()

                cur.execute("""
                    SELECT 
                        (CASE WHEN cr.agent_id = %s THEN u.id ELSE a.id END) as id,
                        (CASE WHEN cr.agent_id = %s THEN u.first_name ELSE a.first_name END) as first_name,
                        (CASE WHEN cr.agent_id = %s THEN u.last_name ELSE a.last_name END) as last_name,
                        (CASE WHEN cr.agent_id = %s THEN u.profile_image ELSE a.profile_image END) as profile_image,
                        (CASE WHEN cr.agent_id = %s THEN u.role ELSE a.role END) as role
                    FROM chat_rooms cr
                    LEFT JOIN users u ON cr.user_id = u.id
                    LEFT JOIN users a ON cr.agent_id = a.id
                    WHERE cr.id = %s;
                """, (user_id, user_id, user_id, user_id, user_id, clean_chat_id))
                raw_partner = cur.fetchone()
                
                if raw_partner:
                    p_img = raw_partner.get("profile_image")
                    if not p_img or not str(p_img).strip():
                        p_img = "default_user.png"
                    
                    active_chat_partner = {
                        "id": raw_partner["id"],
                        "first_name": raw_partner["first_name"] if raw_partner["first_name"] else "User",
                        "last_name": raw_partner["last_name"] if raw_partner["last_name"] else f"#{raw_partner['id']}",
                        "profile_image": p_img,
                        "role": raw_partner["role"] if raw_partner["role"] else "User"
                    }

                cur.execute("""
                    SELECT p.id, p.name, p.price_normalized, p.currency_code
                    FROM chat_rooms cr
                    JOIN properties p ON cr.property_id = p.id
                    WHERE cr.id = %s;
                """, (clean_chat_id,))
                prop_row = cur.fetchone()
                if prop_row:
                    db_currency = prop_row.get("currency_code")
                    currency_symbols = {
                        "GBP": "£", "EUR": "€", "USD": "$", "TL": "₺", "TRY": "₺"
                    }
                    symbol = currency_symbols.get(db_currency, "₺")
                    
                    try:
                        price_val = prop_row.get('price_normalized')
                        if isinstance(price_val, (int, float)):
                            formatted_price = f"{price_val:,}"
                        else:
                            formatted_price = f"{int(price_val):,}" if str(price_val).isdigit() else str(price_val)
                    except Exception:
                        formatted_price = str(prop_row.get('price_normalized', '0'))
                    
                    active_property = {
                        "name": prop_row["name"],
                        "price": f"{formatted_price} {symbol}"
                    }

                cur.execute("""
                    SELECT id, room_id, sender_id, message_text, is_read, created_at
                    FROM chat_messages WHERE room_id = %s ORDER BY id ASC;
                """, (clean_chat_id,))
                active_messages = cur.fetchall()
                
                for m in active_messages:
                    m_time = m["created_at"]
                    if m_time and hasattr(m_time, "strftime"):
                        if m_time.tzinfo is not None:
                            tr_m_time = m_time.astimezone(tr_tz)
                        else:
                            tr_m_time = tr_tz.localize(m_time) if hasattr(tr_tz, 'localize') else m_time.replace(tzinfo=tr_tz)
                        time_str_iso = tr_m_time.strftime("%H:%M")
                    else:
                        time_str_iso = ""
                    
                    messages.append({
                        "id": m["id"],
                        "room_id": m["room_id"],
                        "sender_id": m["sender_id"],
                        "message_text": m["message_text"],
                        "is_read": m["is_read"],
                        "created_at": time_str_iso
                    })

            cur.close()
        except Exception as e:
            print(f"Chat yükleme hatası: {e}")
        finally:
            conn.close()

    return templates.TemplateResponse(request, "messages.html", {
        "role": role,
        "is_admin": get_admin_status(),
        "first_name": user_data.get("first_name", ""),
        "last_name": user_data.get("last_name", ""),
        "profile_image": user_data.get("profile_image", "default_user.png"),
        "p_page": "messages",
        "conversations": conversations,
        "active_conversation_id": clean_chat_id,
        "active_chat_partner": active_chat_partner,
        "active_property": active_property,
        "messages": messages,
        "current_user_id": user_id,
        "unread_messages_count": unread_messages_count
    })

@router.get("/favourites", response_class=HTMLResponse)
async def my_favourites(request: Request):
    """Favoriler Sayfası"""
    _, user_data = get_safe_current_user()
    return templates.TemplateResponse(request, "favourites.html", {
        "role": getattr(db, "current_user_role", "user"),
        "is_admin": get_admin_status(),
        "first_name": user_data.get("first_name", ""),
        "last_name": user_data.get("last_name", ""),
        "profile_image": user_data.get("profile_image", "default_user.png"),
        "p_page": "favourites"
    })

# --- ROL DEĞİŞTİRME ROTALARI ---

@router.get("/switch-to-agent")
async def switch_to_agent(request: Request):
    user_email, user_data = get_safe_current_user()
    if not user_email:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    if user_data and user_data.get("iban") and user_data.get("id_no"):
        db.current_user_role = "agent"
        db.update_user_in_db(user_email, {"role": "agent", "first_name": user_data.get('first_name', ''), "last_name": user_data.get('last_name', '')})
        if hasattr(db, "current_user_data") and isinstance(db.current_user_data, dict):
            db.current_user_data["role"] = "agent"
        return RedirectResponse(url="/profile/personal-info", status_code=status.HTTP_303_SEE_OTHER)
    
    return templates.TemplateResponse(request, "choose_role.html", {
        "role": getattr(db, "current_user_role", "user"), 
        "is_admin": get_admin_status()
    })

@router.post("/upgrade-to-agent")
async def upgrade_to_agent(
    request: Request,
    iban: str = Form(...),
    id_no: str = Form(...),
    company_name: Optional[str] = Form(default=None)
):
    user_email, user_data = get_safe_current_user()
    if not user_email:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    db.current_user_role = "agent"
    
    update_data = {
        "role": "agent", 
        "iban": iban, 
        "id_no": id_no, 
        "company_name": company_name,
        "first_name": user_data.get('first_name', ''),
        "last_name": user_data.get('last_name', '')
    }
    
    db.update_user_in_db(user_email, update_data)
    if hasattr(db, "current_user_data") and isinstance(db.current_user_data, dict):
        db.current_user_data.update(update_data)
    
    return RedirectResponse(url="/profile/personal-info", status_code=status.HTTP_303_SEE_OTHER)

@router.get("/switch-to-user")
async def switch_to_user():
    user_email, user_data = get_safe_current_user()
    if not user_email:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    db.current_user_role = "user"
    
    db.update_user_in_db(user_email, {
        "role": "user", 
        "first_name": user_data.get('first_name', ''), 
        "last_name": user_data.get('last_name', '')
    })
    if hasattr(db, "current_user_data") and isinstance(db.current_user_data, dict):
        db.current_user_data["role"] = "user"
        
    return RedirectResponse(url="/profile/personal-info", status_code=status.HTTP_303_SEE_OTHER)

# --- DİĞER ROTALAR ---

@router.get("/transactions", response_class=HTMLResponse)
async def my_transactions(request: Request):
    _, user_data = get_safe_current_user()
    return templates.TemplateResponse(request, "transactions.html", {
        "role": getattr(db, "current_user_role", "user"),
        "is_admin": get_admin_status(),
        "first_name": user_data.get("first_name", ""),
        "last_name": user_data.get("last_name", ""),
        "profile_image": user_data.get("profile_image", "default_user.png"),
        "p_page": "transactions"
    })

@router.get("/properties", response_class=HTMLResponse)
async def agent_properties(request: Request):
    """Emlakçının kendi ilanlarını gördüğü sayfa"""
    _, user_data = get_safe_current_user()
    
    agent_id = user_data.get("id")
    agent_props = []
    if agent_id:
        try:
            _, agent_props = db.get_agent_with_properties(agent_id)
        except Exception as e:
            print(f"İlan getirme hatası: {e}")
    
    return templates.TemplateResponse(request, "properties.html", {
        "role": getattr(db, "current_user_role", "user"),
        "is_admin": get_admin_status(),
        "first_name": user_data.get("first_name", ""),
        "last_name": user_data.get("last_name", ""),
        "profile_image": user_data.get("profile_image", "default_user.png"),
        "properties": agent_props,
        "p_page": "properties"
    })

@router.get("/requests", response_class=HTMLResponse)
async def agent_requests(request: Request):
    _, user_data = get_safe_current_user()
    return templates.TemplateResponse(request, "requests.html", {
        "role": getattr(db, "current_user_role", "user"),
        "is_admin": get_admin_status(),
        "first_name": user_data.get("first_name", ""),
        "last_name": user_data.get("last_name", ""),
        "profile_image": user_data.get("profile_image", "default_user.png"),
        "p_page": "requests"
    })

@router.get("/payment", response_class=HTMLResponse)
async def agent_payment_page(request: Request):
    _, user_data = get_safe_current_user()
    return templates.TemplateResponse(request, "payment.html", {
        "role": getattr(db, "current_user_role", "user"),
        "is_admin": get_admin_status(),
        "first_name": user_data.get("first_name", ""),
        "last_name": user_data.get("last_name", ""),
        "profile_image": user_data.get("profile_image", "default_user.png"),
        "p_page": "payment"
    })

# --- DİNAMİK İLAN SİLME / KALDIRMA API ENDPOINT ---

@router.delete("/api/property/delete/{property_id}")
async def delete_property(property_id: int):
    """properties.html üzerinden tetiklenen dinamik ilan silme işleyicisi"""
    try:
        success = db.delete_property_from_db(property_id)
        if success:
            return {"status": "success", "message": "İlan başarıyla kaldırıldı."}
        else:
            return {"status": "error", "message": "İlan bulunamadı veya silinemedi."}
    except Exception as e:
        print(f"İlan silme hatası: {e}")
        return {"status": "error", "message": str(e)}

# --- HESAPLAMA ---

@router.post("/calculate-booking")
async def calculate_booking(
    request: Request, 
    property_id: str = Form(...), 
    check_in: str = Form(...), 
    check_out: str = Form(...), 
    nights: int = Form(...), 
    guest_info: str = Form(...)
):
    properties_from_db = []
    try:
        properties_from_db = db.get_properties_from_db()
    except Exception as e:
        print(f"Properties listeleme hatası: {e}")
        
    property_item = next((p for p in properties_from_db if str(p.get('id')) == property_id), None)
    
    if not property_item and hasattr(db, "properties"):
        property_item = db.properties.get(property_id)

    if not property_item:
        return {"error": "Mülk bulunamadı"}
        
    base_price = property_item.get("price", 0) or property_item.get("monthly_price", 0) or 0
    daily_price = base_price / 30
    total_price = round(daily_price * nights, 2)
    
    _, user_data = get_safe_current_user()
    
    return templates.TemplateResponse(request, "payment.html", {
        "property": property_item, 
        "check_in": check_in, 
        "check_out": check_out, 
        "nights": nights, 
        "total_price": total_price, 
        "guest_info": guest_info, 
        "role": getattr(db, "current_user_role", "user"),
        "is_admin": get_admin_status(),
        "first_name": user_data.get("first_name", ""),
        "last_name": user_data.get("last_name", ""),
        "profile_image": user_data.get("profile_image", "default_user.png"),
        "p_page": "payment"
    })