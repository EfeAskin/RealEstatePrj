import os
import shutil  # Dosya transfer işlemleri için
import time  # Benzersiz dosya isimleri üretimi için
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

import database as db  # Veritabanı bağlantısı katmanı
import uvicorn
import pytz  # Zaman dilimi kontrolü için eklendi
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from psycopg2.extras import RealDictCursor
from routers import admin, auth, chat, listings, profile  # Tüm alt modüller dahil edildi

app = FastAPI()

# Projenin ana dizinini belirle
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Şablon ve Statik dosya yollarını bağla
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Zaman dilimi tanımlamaları
tr_tz = pytz.timezone("Europe/Istanbul")

# --- STATİK DOSYA AYARLARI ---
# 1. Genel statik klasörünü bağla (/static/... şeklinde erişim için)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

# 2. Resimlerin doğrudan bulunabilmesi için (/htmlfotos/... şeklinde doğrudan erişim desteği)
app.mount("/htmlfotos", StaticFiles(directory=os.path.join(BASE_DIR, "static/htmlfotos")), name="htmlfotos_direct")

# Modülleri (Auth, Listings, Profile, Admin, Chat) sisteme dahil et
app.include_router(auth.router)
app.include_router(listings.router)
app.include_router(profile.router)
app.include_router(admin.router)
app.include_router(chat.router)


# --- JINJA2 SİHİRLİ ŞABLONLARI İÇİN AKILLI ESNEK SINIFLAR ---
class CallableDict(dict):
    """
    Jinja2 şablonlarında hem düz bir sözlük/string gibi,
    hem de parantez açılarak fonksiyon gibi çağrılabilen akıllı nesne sınıfı.
    Bu sınıf 'is undefined' hatalarını tamamen ortadan kaldırır.
    """
    def __call__(self, *args, **kwargs):
        return self

    def __getattr__(self, item):
        return self.get(item, "")


class CallableStr(str):
    """Jinja2 şablonlarında fonksiyon gibi çağrılabilen akıllı string sınıfı."""
    def __call__(self, *args, **kwargs):
        return self


# --- DİNAMİK OTURUM VE TEMPLATE BAĞLANTISI (MIDDLEWARE) ---
@app.middleware("http")
async def db_session_middleware(request: Request, call_next):
    """
    Bu middleware, her sayfa isteğinde tarayıcının çerezini okur,
    kullanıcıyı veritabanından çözümler ve Jinja2 şablonlarının
    doğru hesabı render etmesini sağlar.
    Ayrıca tüm sayfalarda bildirim sembolünün yanması için
    okunmamış mesaj sayısını chat_messages tablosundan çekerek küresel olarak bağlar.
    """
    user_id_cookie = request.cookies.get("user_id")
    current_user = None
    unread_count = 0
   
    if user_id_cookie:
        try:
            current_user = db.get_user_from_cookie(user_id_cookie)
        except Exception as e:
            print(f"Middleware Kullanıcı Çerez Okuma Hatası: {e}")
            current_user = None
   
    if current_user:
        safe_user_data = CallableDict(current_user)
        safe_user_role = CallableStr(current_user.get("role", "guest"))
       
        templates.env.globals["current_user_role"] = safe_user_role
        templates.env.globals["current_user_data"] = safe_user_data
       
        db.current_user_role = current_user.get("role", "guest")
        db.current_user_data = current_user
        db.current_user_email = current_user.get("email")
       
        # --- KÜRESEL OKUNMAMIŞ MESAJ SAYMA MOTORU ---
        current_user_id = current_user.get("id")
        if current_user_id:
            conn = db.get_db_connection()
            if conn:
                try:
                    cur = conn.cursor()
                    # Kural: Sadece karşı taraftan gelen (m.sender_id != kendi_id'miz)
                    # ve dahil olduğumuz odalardaki okunmamış mesajları sayar.
                    cur.execute(
                        """
                        SELECT COUNT(*) FROM chat_messages m
                        JOIN chat_rooms r ON m.room_id = r.id
                        WHERE (r.user_id = %s OR r.agent_id = %s)
                        AND m.sender_id != %s
                        AND m.is_read = FALSE
                        AND r.is_ai_chat = FALSE
                        """,
                        (int(current_user_id), int(current_user_id), int(current_user_id))
                    )
                    row = cur.fetchone()
                    unread_count = row[0] if row else 0
                    cur.close()
                except Exception as e:
                    print(f"Middleware Okunmamış Mesaj Sayma Hatası: {e}")
                finally:
                    conn.close()
    else:
        empty_user_data = CallableDict({})
        guest_role = CallableStr("guest")
       
        templates.env.globals["current_user_role"] = guest_role
        templates.env.globals["current_user_data"] = empty_user_data
       
        db.current_user_role = "guest"
        db.current_user_data = {}
        db.current_user_email = None

    templates.env.globals["unread_messages_count"] = unread_count

    response = await call_next(request)
    return response


# Ana sayfa yönlendirmesi
@app.get("/")
async def root(request: Request):
    return RedirectResponse(url="/home", status_code=303)


# ==============================================================================
# PROFİL MESAJLAŞMA ENDPOINT'LERİ (ZAMAN, SOL-SAĞ BALONCUK VE AVATAR UYUMLULUĞU)
# ==============================================================================
@app.get("/profile/messages")
async def get_profile_messages(request: Request, chat_id: Optional[int] = None):
    """
    Sol taraftaki sohbet odalarını çeken, tıklanan odanın ID'sini URL'e basan,
    kullanıcı adlarını ve profil resimlerini static/htmlfotos altından dinamik getiren,
    odeya girildiğinde unread_count bildirimlerini sıfırlayan ana sayfa endpoint'i.
    Zaman dilimi kaymaları hem yerel (naive) hem de timezone duyarlı nesneler için fixlendi.
    """
    user_id_cookie = request.cookies.get("user_id")
    current_user = db.get_user_from_cookie(user_id_cookie) if user_id_cookie else None
   
    if not current_user:
        return RedirectResponse(url="/auth/login", status_code=303)
       
    current_user_id = int(current_user.get("id"))
   
    conn = db.get_db_connection()
    if not conn:
        return templates.TemplateResponse("messages.html", {"request": request, "chats": [], "messages": [], "error": "Veritabanı bağlantı hatası."})
       
    chats_list = []
    messages_list = []
    active_chat_user_name = None
    active_chat_user_avatar = None
   
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
       
        # 1. ADIM: AKTİF SOHBET ODALARI LİSTESİNİ VE KARŞI TARAFIN BİLGİLERİNİ ÇEKME
        cur.execute(
            """
            SELECT
                cr.id AS chat_id,
                u.id AS counterpart_id,
                u.first_name,
                u.last_name,
                u.profile_image,
                (SELECT cm.message_text FROM chat_messages cm WHERE cm.room_id = cr.id ORDER BY cm.created_at DESC LIMIT 1) AS last_message,
                (SELECT COUNT(*) FROM chat_messages cm WHERE cm.room_id = cr.id AND cm.is_read = FALSE AND cm.sender_id != %s) AS unread_count
            FROM chat_rooms cr
            JOIN users u ON (
                (cr.user_id = u.id AND cr.agent_id = %s) OR
                (cr.agent_id = u.id AND cr.user_id = %s)
            )
            WHERE (cr.user_id = %s OR cr.agent_id = %s) AND cr.is_ai_chat = FALSE;
            """,
            (current_user_id, current_user_id, current_user_id, current_user_id, current_user_id)
        )
        db_chats = cur.fetchall()
       
        for row in db_chats:
            prof_img = str(row["profile_image"]).strip() if row["profile_image"] else ""
            if prof_img:
                if prof_img.startswith("static/") or prof_img.startswith("/static/"):
                    avatar_path = prof_img if prof_img.startswith("/") else f"/{prof_img}"
                elif prof_img.startswith("htmlfotos/"):
                    avatar_path = f"/static/{prof_img}"
                else:
                    avatar_path = f"/static/htmlfotos/{prof_img}"
            else:
                avatar_path = "/static/htmlfotos/default_user.png"
               
            chats_list.append({
                "id": row["chat_id"],
                "user_name": f"{row['first_name']} {row['last_name']}".strip() or f"Kullanıcı #{row['counterpart_id']}",
                "user_avatar": avatar_path,
                "last_message": row["last_message"] if row["last_message"] else "Henüz mesaj yok.",
                "unread_count": int(row["unread_count"])
            })
           
        # 2. ADIM: EĞER BİR ODA SEÇİLDİYSE MESAJLARI GETİR VE OKUNDU YAP
        if chat_id:
            cur.execute(
                """
                UPDATE chat_messages
                SET is_read = TRUE
                WHERE room_id = %s AND sender_id != %s;
                """,
                (chat_id, current_user_id)
            )
            conn.commit()
           
            # [ZAMAN REBORN]: Katlamalı +3 saat hatasını düzeltmek adına SQL'deki çifte TIME ZONE dönüşümü temizlendi.
            cur.execute(
                """
                SELECT sender_id, message_text, created_at
                FROM chat_messages
                WHERE room_id = %s
                ORDER BY created_at ASC;
                """,
                (chat_id,)
            )
            db_messages = cur.fetchall()
           
            for m in db_messages:
                m_time = m["created_at"]
                time_str = ""
                if m_time and hasattr(m_time, "strftime"):
                    # Saatin üst üste binmesini engelleyecek kontrollü dönüşüm mantığı
                    if m_time.tzinfo is not None:
                        localized_time = m_time.astimezone(tr_tz)
                    else:
                        localized_time = tr_tz.localize(m_time) if hasattr(tr_tz, 'localize') else m_time.replace(tzinfo=tr_tz)
                    time_str = localized_time.strftime("%H:%M")

                messages_list.append({
                    "sender_id": m["sender_id"],
                    "content": m["message_text"],
                    "timestamp": time_str,
                    "is_my_message": int(m["sender_id"]) == current_user_id
                })
               
            for c in chats_list:
                if int(c["id"]) == int(chat_id):
                    active_chat_user_name = c["user_name"]
                    active_chat_user_avatar = c["user_avatar"]
                    c["unread_count"] = 0

        cur.close()
    except Exception as e:
        print(f"Sohbet Sayfası Yükleme Hatası: {e}")
    finally:
        conn.close()
           
    return templates.TemplateResponse(
        "messages.html",
        {
            "request": request,
            "chats": chats_list,
            "messages": messages_list,
            "current_chat_id": chat_id,
            "current_user_id": current_user_id,
            "active_chat_user_name": active_chat_user_name,
            "active_chat_user_avatar": active_chat_user_avatar
        }
    )


@app.post("/profile/messages/send")
async def send_profile_message(
    request: Request,
    chat_id: int = Form(...),
    message_content: str = Form(...)
):
    """Sohbet odası içerisinden gönderilen yeni mesajları mükerrer kayıt korumasıyla veritabanına yazar."""
    user_id_cookie = request.cookies.get("user_id")
    current_user = db.get_user_from_cookie(user_id_cookie) if user_id_cookie else None
   
    if not current_user:
        return RedirectResponse(url="/auth/login", status_code=303)
       
    current_user_id = current_user.get("id")
    clean_message = message_content.strip()
   
    if not clean_message:
        return RedirectResponse(url=f"/profile/messages?chat_id={chat_id}", status_code=303)
       
    conn = db.get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
           
            # [ÇİFT KAYIT KORUMASI]: Aynı odada, aynı kişinin son 2 saniyede attığı birebir aynı mesaj var mı kontrol et
            cur.execute(
                """
                SELECT id FROM chat_messages
                WHERE room_id = %s AND sender_id = %s AND message_text = %s
                AND created_at >= NOW() - INTERVAL '2 second'
                LIMIT 1;
                """,
                (chat_id, current_user_id, clean_message)
            )
            duplicate = cur.fetchone()
           
            # Eğer kayıt zaten mevcutsa ikinci kez ekleme yapmadan doğrudan sayfaya yönlendir
            if duplicate:
                cur.close()
                return RedirectResponse(url=f"/profile/messages?chat_id={chat_id}", status_code=303)

            # Mükerrer değilse güvenle kaydet
            cur.execute(
                """
                INSERT INTO chat_messages (room_id, sender_id, message_text, is_from_ai, is_read, created_at)
                VALUES (%s, %s, %s, FALSE, FALSE, NOW());
                """,
                (chat_id, current_user_id, clean_message)
            )
            conn.commit()
            cur.close()
        except Exception as e:
            print(f"Mesaj Kaydedilirken Kritik Hata: {e}")
            conn.rollback()
        finally:
            conn.close()
               
    return RedirectResponse(url=f"/profile/messages?chat_id={chat_id}", status_code=303)


# ==============================================================================
# İLAN SAYFASINDAN SOHBET TETİKLEME ENDPOINT'İ
# ==============================================================================
@app.post("/chat/initiate/{property_id}")
async def initiate_chat(property_id: int, request: Request):
    """Sohbet odası oluşturma veya var olan odayı getirme endpoint'i."""
    user_id_cookie = request.cookies.get("user_id")
    user_data = db.get_user_from_cookie(user_id_cookie) if user_id_cookie else None
   
    if not user_data:
        return JSONResponse(status_code=401, content={"error": "Sohbet başlatmak için giriş yapmalısınız."})
       
    current_user_id = user_data.get("id")
    if not current_user_id:
        return JSONResponse(status_code=401, content={"error": "Kullanıcı oturum bilgisi geçersiz."})

    conn = db.get_db_connection()
    if not conn:
        return JSONResponse(status_code=500, content={"error": "Veritabanı bağlantı hatası."})
       
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, name, agent_id FROM properties WHERE id = %s", (property_id,))
        prop = cur.fetchone()
       
        if not prop:
            cur.close()
            return JSONResponse(status_code=404, content={"error": "İlan bulunamadı."})
           
        target_agent_id = prop.get("agent_id")
        if not target_agent_id:
            cur.close()
            return JSONResponse(status_code=400, content={"error": "Bu ilana ait bir emlakçı bulunamadı."})

        if int(current_user_id) == int(target_agent_id):
            cur.close()
            return JSONResponse(status_code=400, content={"error": "Kendi ilanınız için sohbet başlatamazsınız."})

        cur.execute(
            """
            SELECT id FROM chat_rooms
            WHERE property_id = %s AND user_id = %s AND agent_id = %s AND is_ai_chat = FALSE
            """,
            (property_id, current_user_id, target_agent_id)
        )
        room = cur.fetchone()
       
        if room:
            room_id = room["id"]
        else:
            cur.execute(
                """
                INSERT INTO chat_rooms (property_id, user_id, agent_id, is_ai_chat)
                VALUES (%s, %s, %s, FALSE) RETURNING id
                """,
                (property_id, current_user_id, target_agent_id)
            )
            room_id = cur.fetchone()["id"]
            conn.commit()
           
        cur.close()
        return {
            "room_id": room_id,
            "agent_id": target_agent_id,
            "name": prop.get("name"),
            "title": prop.get("name")
        }
       
    except Exception as e:
        conn.rollback()
        print(f"Kritik /chat/initiate Hatası: {e}")
        return JSONResponse(status_code=500, content={"error": f"Veritabanı hatası: {str(e)}"})
    finally:
        conn.close()


# ==============================================================================
# YENİ İLAN EKLEME ENDPOINT (Pop-up Formu Yönetimi)
# ==============================================================================
@app.post("/add-property")
async def add_property(
    request: Request,
    name: str = Form(...),
    location: str = Form(...),
    price: float = Form(...),
    type: str = Form(...),
    beds: int = Form(0),
    baths: int = Form(0),
    sqm: int = Form(0),
    open_m2: int = Form(0),
    guests: int = Form(0),
    is_site: str = Form("Hayır"),
    site_name: str = Form("-"),
    is_credit: str = Form("Hayır"),
    is_trade: str = Form("Hayır"),
    currency_code: str = Form("TRY"),
    deed_status: str = Form("-"),
    description: str = Form(None),
    main_image: UploadFile = File(...)
):
    """Pop-up formdan gelen ilan verilerini resim yükleme kontrolüyle birlikte kaydeder."""
    user_id_cookie = request.cookies.get("user_id")
    user_data = db.get_user_from_cookie(user_id_cookie) if user_id_cookie else None
    user_role = user_data.get("role") if user_data else "guest"
   
    if not user_data or user_role != 'agent':
        return JSONResponse(status_code=401, content={"error": "İlan vermek için Agent hesabı ile giriş yapmalısınız."})

    file_extension = os.path.splitext(main_image.filename)[1].lower()
    if file_extension not in ['.png', '.jpg', '.jpeg', '.webp']:
        return JSONResponse(status_code=400, content={"error": "Sadece resim formatında (.png, .jpg, .jpeg, .webp) dosya yükleyebilirsiniz."})

    upload_folder = os.path.join(BASE_DIR, "static/htmlfotos")
    if not os.path.exists(upload_folder):
        os.makedirs(upload_folder)

    new_filename = f"prop_{int(time.time())}{file_extension}"
    file_path = os.path.join(upload_folder, new_filename)

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(main_image.file, buffer)
    except Exception as e:
        print(f"Dosya kaydetme hatası: {e}")
        return JSONResponse(status_code=500, content={"error": "Dosya yüklenemedi."})

    loc_parts = [p.strip() for p in location.split(',')]
    district = loc_parts[0] if len(loc_parts) > 0 else ""
    city = loc_parts[1] if len(loc_parts) > 1 else ""
    country = loc_parts[2] if len(loc_parts) > 2 else ""

    clean_is_site = is_site if is_site in ["Evet", "Hayır"] else "Hayır"
    clean_site_name = site_name if clean_is_site == "Evet" and site_name else "-"

    if type == "sale":
        clean_is_credit = is_credit if is_credit in ["Evet", "Hayır"] else "Hayır"
        clean_is_trade = is_trade if is_trade in ["Evet", "Hayır"] else "Hayır"
    else:
        clean_is_credit = "Hayır"
        clean_is_trade = "Hayır"

    property_data = {
        "name": name,
        "title": name,
        "location": location,      
        "district": district,      
        "city": city,              
        "country": country,        
        "price": price,            
        "price_normalized": price,
        "type": type,              
        "listing_type": type,      
        "beds": beds,
        "baths": baths,
        "sqm": sqm,
        "open_m2": open_m2,
        "guests": guests,
        "is_site": clean_is_site,
        "site_name": clean_site_name,
        "is_credit": clean_is_credit,
        "is_trade": clean_is_trade,
        "currency": currency_code,    
        "currency_code": currency_code,
        "deed_status": deed_status,
        "description": description,
        "image": f"htmlfotos/{new_filename}",
        "status": "approving"
    }

    agent_id = user_data.get('id')
    clean_agent_id = int(agent_id) if str(agent_id).isdigit() else agent_id
   
    try:
        success = db.add_new_property_to_db(clean_agent_id, property_data)
    except Exception as e:
        print(f"Veritabanı ekleme fonksiyonu hatası: {e}")
        success = False

    if success:
        return RedirectResponse(url="/profile/properties", status_code=303)
    else:
        if os.path.exists(file_path):
            os.remove(file_path)
        return JSONResponse(status_code=500, content={"error": "Veritabanı kaydı sırasında bir hata oluştu."})


# --- ÖZELLİKLERİ ÇEKEN API ---
@app.get("/api/features")
async def get_features():
    """Neon PostgreSQL üzerindeki 'features' tablosundan tüm verileri çeker."""
    try:
        features = db.get_all_features_from_db()
        return features
    except Exception as e:
        print(f"API Hatası (Features): {e}")
        return []


# ==============================================================================
# MODAL DÜZENLEME VE VERİ UYUMLULUK API ENDPOINT'LERİ
# ==============================================================================
@app.get("/api/property/{property_id}")
async def get_single_property_api(property_id: str):
    """Modal formunu doldurabilmek için ilan verilerini JSON dönen API ucu."""
    try:
        clean_id = int(property_id) if str(property_id).isdigit() else property_id
        prop = None
       
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
            safe_prop = {}
            for key, value in dict(prop).items():
                if isinstance(value, Decimal):
                    safe_prop[key] = float(value)
                elif isinstance(value, datetime):
                    safe_prop[key] = value.isoformat()
                elif isinstance(value, list):
                    safe_prop[key] = value
                elif value is None:
                    if key in ['price', 'price_normalized', 'dues', 'monthly_price', 'gross_m2', 'net_m2', 'beds', 'baths', 'guests', 'open_m2']:
                        safe_prop[key] = 0
                    elif key in ['is_site', 'is_credit', 'is_trade']:
                        safe_prop[key] = "Hayır"
                    else:
                        safe_prop[key] = ""
                else:
                    safe_prop[key] = value

            # Alias Uyuşmazlık Yönetimi
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


@app.post("/api/property/update/{property_id}")
async def update_property_endpoint(property_id: str, request: Request):
    """Düzenleme modalı onaylandığında veritabanını güncelleyen uç nokta."""
    try:
        form_data = await request.form()
        update_data = {}

        if "title" in form_data:
            update_data["name"] = form_data.get("title")
            update_data["title"] = form_data.get("title")
        if "name" in form_data and "title" not in form_data:
            update_data["name"] = form_data.get("name")
            update_data["title"] = form_data.get("name")
           
        if "location" in form_data: update_data["location"] = form_data.get("location")
        if "description" in form_data: update_data["description"] = form_data.get("description")
        if "status" in form_data: update_data["status"] = form_data.get("status")
       
        if "currency" in form_data:
            update_data["currency"] = form_data.get("currency")
            update_data["currency_code"] = form_data.get("currency")
        if "currency_code" in form_data and "currency" not in form_data:
            update_data["currency"] = form_data.get("currency_code")
            update_data["currency_code"] = form_data.get("currency_code")
           
        if "deed_status" in form_data: update_data["deed_status"] = form_data.get("deed_status")
        if "site_name" in form_data: update_data["site_name"] = form_data.get("site_name")
       
        if "type" in form_data:
            update_data["type"] = form_data.get("type")
            update_data["listing_type"] = form_data.get("type")
        if "listing_type" in form_data and "type" not in form_data:
            update_data["type"] = form_data.get("listing_type")
            update_data["listing_type"] = form_data.get("listing_type")
           
        if "is_site" in form_data: update_data["is_site"] = form_data.get("is_site")
        if "is_credit" in form_data: update_data["is_credit"] = form_data.get("is_credit")
        if "is_trade" in form_data: update_data["is_trade"] = form_data.get("is_trade")

        if "price" in form_data and form_data.get("price") != "":
            update_data["price"] = float(form_data.get("price"))
            update_data["price_normalized"] = float(form_data.get("price"))
        if "beds" in form_data and form_data.get("beds") != "":
            update_data["beds"] = int(form_data.get("beds"))
        if "baths" in form_data and form_data.get("baths") != "":
            update_data["baths"] = int(form_data.get("baths"))
        if "sqm" in form_data and form_data.get("sqm") != "":
            update_data["sqm"] = int(form_data.get("sqm"))
           
        if "open_m2" in form_data and form_data.get("open_m2") != "":
            update_data["open_m2"] = int(form_data.get("open_m2"))
        elif "open_area_m2" in form_data and form_data.get("open_area_m2") != "":
            update_data["open_m2"] = int(form_data.get("open_area_m2"))
           
        if "guests" in form_data and form_data.get("guests") != "":
            update_data["guests"] = int(form_data.get("guests"))
        elif "capacity" in form_data and form_data.get("capacity") != "":
            update_data["guests"] = int(form_data.get("capacity"))

        features_list = form_data.getlist("features")
        if features_list:
            update_data["features"] = [int(f) for f in features_list if str(f).isdigit()]
       
        images_list = form_data.getlist("images")
        if images_list:
            update_data["images"] = [str(img) for img in images_list if img]

        if "location" in update_data and update_data["location"]:
            loc_parts = [p.strip() for p in update_data["location"].split(',')]
            update_data["district"] = loc_parts[0] if len(loc_parts) > 0 else ""
            update_data["city"] = loc_parts[1] if len(loc_parts) > 1 else ""
            update_data["country"] = loc_parts[2] if len(loc_parts) > 2 else ""

        clean_id = int(property_id) if str(property_id).isdigit() else property_id

        user_id_cookie = request.cookies.get("user_id")
        user_data = db.get_user_from_cookie(user_id_cookie) if user_id_cookie else None
        user_role = user_data.get("role") if user_data else "guest"

        success = False
        if hasattr(db, 'update_property_in_db'):
            success = db.update_property_in_db(clean_id, update_data)
        elif hasattr(db, 'update_property_status') and "status" in update_data and len(update_data) == 1:
            success = db.update_property_status(clean_id, update_data["status"])
        else:
            success = True

        if success:
            redirect_url = "/admin/all-properties" if user_role == "admin" else "/profile/properties"
            return RedirectResponse(url=redirect_url, status_code=303)
        else:
            return JSONResponse(status_code=400, content={"error": "Veritabanı güncelleme hatası."})
           
    except Exception as e:
        print(f"Kritik Güncelleme Hatası Logu: {str(e)}")
        return JSONResponse(status_code=500, content={"error": f"Sunucu hatası: {str(e)}"})


if __name__ == "__main__":
    uvicorn.run("backend:app", host="127.0.0.1", port=8000, reload=True)