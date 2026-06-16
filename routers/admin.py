from fastapi import APIRouter, Depends, Request, status, HTTPException, Body, Form, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import database as db
from psycopg2.extras import RealDictCursor
import os
import time
import shutil
from datetime import datetime
from decimal import Decimal
import math
from typing import List, Optional

# PERFORMANS: Her admin isteğinde taze bir psycopg2.connect() açmak yerine (Neon'a
# karşı her seferinde ~0.6s'lik TLS/handshake) paylaşımlı bağlantı havuzunu kullan.
from db.connection import get_db_connection
from routers.profile import get_admin_status, get_safe_current_user, get_safe_current_user

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="templates")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# SECURITY BARRIER + PERFORMANS: istek-bazlı kullanıcıyı tek seferde çözer.
# Middleware kullanıcıyı zaten çözüp request.state.user'a koyduğu için burada
# tekrar DB sorgusu yapmadan onu kullanırız; admin değilse None döner.
def get_admin_user(request):
    """Returns the request's user dict if they are an admin, else None.

    Reuses the middleware-resolved (cached) user from request.state to avoid an
    extra per-page DB round trip; falls back to a direct lookup if absent."""
    user = getattr(getattr(request, "state", None), "user", None)
    if user is None:
        user = db.get_user_from_request(request)
    return user if db.is_admin_user(user) else None


def verify_admin(request):
    """Backwards-compatible boolean guard (kept for the mutation endpoints)."""
    return get_admin_user(request) is not None


# =========================================================
# 1. LIST ALL SYSTEM PROPERTIES PAGE (GET)
# =========================================================
@router.get("/all-properties", response_class=HTMLResponse)
async def admin_all_properties(request: Request):
    """Page where the admin can view all listings in the system"""
    user_data = get_admin_user(request)
    if not user_data:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

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
    # Newly added listings awaiting approval (status = 'pending') are not listed on this page.
    # The buttons here are only intended to switch inactive listings to active (or vice versa).
    all_props = []
    for p in all_props_raw:
        if str(p.get('status') or '').lower() not in ('pending', 'approving'):
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
        "role": user_data.get("role", "admin"),
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
    user_data = get_admin_user(request)
    if not user_data:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

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
        "role": user_data.get("role", "admin"),
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
    user_data = get_admin_user(request)
    if not user_data:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

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
            WHERE LOWER(TRIM(p.status)) IN ('pending', 'approving')
            ORDER BY p.id DESC
        """
        cur.execute(query)
        rows = cur.fetchall()

        # rows tüm elemanları çektiği için len(rows) bize veritabanındaki GERÇEK TOPLAM onay bekleyen sayısını verir (Örn: 7)
        total_count = len(rows)

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
        "role": user_data.get("role", "admin"),
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
    user_data = get_admin_user(request)
    if not user_data:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    # Fetch real counts in ONE round trip (3 separate COUNT queries = 3x Neon latency).
    stats = {"total_properties": 0, "pending_approvals": 0, "total_users": 0}
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM properties) AS total_properties,
                (SELECT COUNT(*) FROM properties WHERE LOWER(TRIM(status)) IN ('pending', 'approving')) AS pending_approvals,
                (SELECT COUNT(*) FROM users) AS total_users
            """
        )
        row = cur.fetchone()
        if row:
            stats["total_properties"] = row[0]
            stats["pending_approvals"] = row[1]
            stats["total_users"] = row[2]
    except Exception as e:
        print(f"Dashboard statistics gather error: {e}")
    finally:
        if cur: cur.close()
        if conn: conn.close()

    return templates.TemplateResponse(request, "dashboard.html", {
        "role": user_data.get("role", "admin"),
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
    user_data = get_admin_user(request)
    if not user_data:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    logs = get_system_logs_from_db()

    return templates.TemplateResponse(request, "system_logs.html", {
        "role": user_data.get("role", "admin"),
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
    user_data = get_admin_user(request)
    if not user_data:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    sales = get_sales_logs_from_db()

    return templates.TemplateResponse(request, "sales_logs.html", {
        "role": user_data.get("role", "admin"),
        "is_admin": True,
        "p_page": "sales-logs",
        "first_name": user_data.get("first_name", ""),
        "last_name": user_data.get("last_name", ""),
        "profile_image": user_data.get("profile_image", "default_user.png"),
        "sales": sales
    })
    
from fastapi import APIRouter, Request, Body, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor

# =========================================================================
# 1. BİLET ANA SAYFA ROTASI
# =========================================================================
from fastapi import APIRouter, Request, Body, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor

# =========================================================================
# 1. BİLET ANA SAYFA ROTASI
# =========================================================================
@router.get("/admin_tickets", response_class=HTMLResponse)
@router.get("/tickets", response_class=HTMLResponse)
@router.get("/tickets/", response_class=HTMLResponse)
async def my_admin_tickets(request: Request):
    """Admin Tickets Sayfası - SQL Şemasına ve Kullanıcı Tablosuna Tam Uyumlu"""
    _, user_data = get_safe_current_user(request)
    
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # --- 1. Bilet Listesini Çekme ---
        cursor.execute("""
            SELECT t.*, 
                   CONCAT(u.first_name, ' ', u.last_name) as ticket_owner, 
                   u.profile_image,
                   u.role as user_role
            FROM tickets t
            LEFT JOIN users u ON t.sender_id = u.id
            ORDER BY t.created_at DESC
        """)
        raw_tickets = cursor.fetchall()
        
        tickets_list = []
        for t in raw_tickets:
            c_at = t.get('created_at')
            formatted_date = c_at.strftime("%Y-%m-%d %H:%M") if isinstance(c_at, datetime) else None
            
            db_status = t.get('ticket_status') or 'Waiting'
            js_status = db_status.lower()
            
            owner_name = t.get('ticket_owner')
            if not owner_name or owner_name.strip() == "":
                owner_name = f"User #{t.get('sender_id')}"
            
            tickets_list.append({
                "id": t.get('id'),
                "username": owner_name,
                "category": t.get('ticket_type'),
                "subject": t.get('subject') or "Başlıksız Bilet", 
                "status": js_status,
                "user_image": t.get('profile_image') or "default_user.png",
                "role": t.get('user_role') or "user",
                "created_at": formatted_date
            })

        # --- 2. Durum Sayıları (İstatistik Kartları) ---
        # İSTEK: 'Spam' artık kendi kartına/sayısına sahip, 'Success' veya 'Failed'ı etkilemiyor!
        cursor.execute("""
            SELECT 
                COUNT(CASE WHEN ticket_status = 'Waiting' THEN 1 END) as waiting,
                COUNT(CASE WHEN ticket_status = 'Active' THEN 1 END) as active,
                COUNT(CASE WHEN ticket_status = 'Success' THEN 1 END) as success,
                COUNT(CASE WHEN ticket_status = 'Failed' THEN 1 END) as failed,
                COUNT(CASE WHEN ticket_status = 'Spam' THEN 1 END) as spam
            FROM tickets
        """)
        counts = cursor.fetchone() or {'waiting': 0, 'active': 0, 'success': 0, 'failed': 0, 'spam': 0}

        waiting_count = counts.get('waiting') or 0
        stats_data = {
            "waiting": waiting_count,
            "active": counts.get('active') or 0,
            "success": counts.get('success') or 0,
            "failed": counts.get('failed') or 0,
            "spam": counts.get('spam') or 0,
            "total_closed": (counts.get('success') or 0) + (counts.get('failed') or 0) + (counts.get('spam') or 0) # Close sayısını arttırır
        }

        has_waiting_tickets = waiting_count > 0
        stats_data["waiting_count"] = waiting_count

        # --- 3. Kategori Dağılımı ---
        cursor.execute("""
            SELECT 
                COUNT(CASE WHEN ticket_type = 'Support' THEN 1 END) as support,
                COUNT(CASE WHEN ticket_type = 'Bugs' THEN 1 END) as bugs,
                COUNT(CASE WHEN ticket_type = 'Complaints' THEN 1 END) as complaints,
                COUNT(CASE WHEN ticket_type = 'Desire' THEN 1 END) as desire,
                COUNT(CASE WHEN ticket_type = 'Others' THEN 1 END) as others
            FROM tickets
        """)
        cats = cursor.fetchone() or {'support': 0, 'bugs': 0, 'complaints': 0, 'desire': 0, 'others': 0}
        
        categories_data = {
            "Support": cats.get('support') or 0,
            "Bugs": cats.get('bugs') or 0,
            "Complaints": cats.get('complaints') or 0,
            "Desire": cats.get('desire') or 0,
            "Others": cats.get('others') or 0
        }

        # --- 4. 12 Aylık Çizgi Grafik Verisi ---
        current_year = datetime.now().year
        monthly_chart_data = [0] * 12
        
        cursor.execute("""
            SELECT EXTRACT(MONTH FROM created_at) as month, COUNT(id) as count
            FROM tickets
            WHERE EXTRACT(YEAR FROM created_at) = %s
            GROUP BY EXTRACT(MONTH FROM created_at)
        """, (current_year,))
        monthly_counts = cursor.fetchall()
        
        for row in monthly_counts:
            m_idx = int(row.get('month')) - 1
            if 0 <= m_idx < 12:
                monthly_chart_data[m_idx] = row.get('count')

        monthly_total = sum(monthly_chart_data)

    finally:
        cursor.close()
        conn.close()

    return templates.TemplateResponse(request, "admin_tickets.html", {
        "role": "admin",
        "is_admin": get_admin_status(),
        "first_name": user_data.get("first_name", ""),
        "last_name": user_data.get("last_name", ""),
        "profile_image": user_data.get("profile_image", "default_user.png"),
        "p_page": "admin_tickets",
        
        "tickets": tickets_list,
        "stats": stats_data,
        "categories": categories_data,
        "monthly_total": monthly_total,
        "monthly_chart_data": monthly_chart_data,
        "has_waiting_tickets": has_waiting_tickets,
        "waiting_count": waiting_count
    })


# =========================================================================
# 2. API: SOHBET GEÇMİŞİ (404 ENGELLEMEK İÇİN ÇİFT ROTA)
# =========================================================================
@router.get("/tickets/{ticket_id}/messages")
@router.get("/admin/tickets/{ticket_id}/messages")
async def get_ticket_messages(ticket_id: int):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute("""
            SELECT tm.id, tm.message_text, tm.sent_at, tm.sender_id, 
                   t.sender_id as ticket_owner_id,
                   u.profile_image, CONCAT(u.first_name, ' ', u.last_name) as sender_name,
                   u.role as sender_role
            FROM ticket_messages tm
            JOIN tickets t ON tm.ticket_id = t.id
            LEFT JOIN users u ON tm.sender_id = u.id
            WHERE tm.ticket_id = %s 
            ORDER BY tm.sent_at ASC
        """, (ticket_id,))
        messages = cursor.fetchall()
        
        formatted_messages = []
        for msg in messages:
            s_at = msg.get('sent_at')
            is_admin = msg.get('sender_id') != msg.get('ticket_owner_id')
            
            formatted_messages.append({
                "id": msg.get('id'),
                "message": msg.get('message_text'),
                "is_admin": is_admin,
                "sender_name": msg.get('sender_name') or f"User #{msg.get('sender_id')}",
                "user_image": msg.get('profile_image') or "default_user.png",
                "sender_role": msg.get('sender_role') or "user",
                "created_at": s_at.strftime("%Y-%m-%d %H:%M") if isinstance(s_at, datetime) else None
            })
            
        return {"status": "success", "messages": formatted_messages}
    finally:
        cursor.close()
        conn.close()


# =========================================================================
# 3. API: DURUM GÜNCELLEME (RESMİ 'Spam' DESTEKLİ)
# =========================================================================
@router.put("/tickets/{ticket_id}/status")
@router.put("/admin/tickets/{ticket_id}/status")
async def update_ticket_status_api(ticket_id: int, request: Request, payload: dict = Body(...)):
    new_status = payload.get("status")
    if not new_status:
        raise HTTPException(status_code=400, detail="Status boş olamaz.")
    
    db_status = new_status.capitalize()

    if db_status not in ['Waiting', 'Active', 'Success', 'Failed', 'Spam']:
        raise HTTPException(status_code=400, detail=f"Geçersiz durum değeri: {db_status}")
        
    _, admin_user_data = get_safe_current_user(request)
    admin_id = admin_user_data.get("id")

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    auto_msg_added = False
    auto_msg_text = "Talebiniz alınmıştır, yetkili birimlerimiz tarafından detaylı inceleniyor. En kısa sürede buradan dönüş sağlayacağız."
    
    try:
        # Önce bu biletin ŞU ANKİ durumunu kontrol ediyoruz ki mükerrer (üst üste) otomatik mesaj atılmasın
        cursor.execute("SELECT ticket_status FROM tickets WHERE id = %s", (ticket_id,))
        current_ticket = cursor.fetchone()
        
        # Eğer bilet bulunamadıysa hata dön
        if not current_ticket:
            raise HTTPException(status_code=404, detail="Bilet bulunamadı.")
            
        old_db_status = current_ticket.get('ticket_status')

        # Bilet durumunu güncelle
        cursor.execute("""
            UPDATE tickets 
            SET ticket_status = %s, receiver_id = COALESCE(receiver_id, %s)
            WHERE id = %s
        """, (db_status, admin_id, ticket_id))
        
        # ÇÖZÜM: Eğer bilet İLK KEZ Active (Open) durumuna geçiyorsa otomatik mesajı ekle
        if db_status == 'Active' and old_db_status != 'Active':
            cursor.execute("""
                INSERT INTO ticket_messages (ticket_id, sender_id, message_text, sent_at)
                VALUES (%s, %s, %s, NOW())
            """, (ticket_id, admin_id, auto_msg_text))
            auto_msg_added = True

        conn.commit()
        
        # Frontend'e otomatik mesaj eklenip eklenmediğini açıkça söylüyoruz
        return {
            "status": "success", 
            "new_status": new_status.lower(),
            "auto_msg_added": auto_msg_added,
            "auto_msg": auto_msg_text if auto_msg_added else None,
            "admin_name": f"{admin_user_data.get('first_name', '')} {admin_user_data.get('last_name', '')}".strip(),
            "admin_image": admin_user_data.get('profile_image', 'default_user.png')
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()


# =========================================================================
# 4. API: YENİ MESAJ GÖNDERME
# =========================================================================
@router.post("/tickets/{ticket_id}/messages")
@router.post("/admin/tickets/{ticket_id}/messages")
async def send_admin_message_api(ticket_id: int, request: Request, payload: dict = Body(...)):
    message_text = payload.get("message")
    if not message_text or not message_text.strip():
        raise HTTPException(status_code=400, detail="Mesaj içeriği boş olamaz.")
        
    _, admin_user_data = get_safe_current_user(request)
    admin_id = admin_user_data.get("id")
    
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute("""
            INSERT INTO ticket_messages (ticket_id, sender_id, message_text, sent_at)
            VALUES (%s, %s, %s, NOW())
            RETURNING id
        """, (ticket_id, admin_id, message_text.strip()))
        new_id = cursor.fetchone()['id']
        
        cursor.execute("""
            UPDATE tickets 
            SET receiver_id = COALESCE(receiver_id, %s) 
            WHERE id = %s
        """, (admin_id, ticket_id))
        
        conn.commit()
        return {"status": "success", "message_id": new_id}
    finally:
        cursor.close()
        conn.close()


# =========================================================================
# 5. API: GLOBAL BİLDİRİM SAYACI
# =========================================================================
@router.get("/tickets/waiting-count")
@router.get("/admin/tickets/waiting-count")
async def get_waiting_tickets_count():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute("SELECT COUNT(id) as count FROM tickets WHERE ticket_status = 'Waiting'")
        res = cursor.fetchone()
        count = res.get('count') or 0
        return {"status": "success", "waiting_count": count, "has_waiting": count > 0}
    except:
        return {"status": "error", "waiting_count": 0, "has_waiting": False}
    finally:
        cursor.close()
        conn.close()


# =========================================================
# 7. DELETE / DEACTIVATE PROPERTY ENDPOINT (POST)
# =========================================================
@router.post("/delete-property/{property_id}")
async def admin_delete_property_endpoint(property_id: str, request: Request):
    """
    Yönetici panelinden (all-properties veya approving) gelen silme/pasife alma isteği.
    İlanın durumunu doğrudan 'inactive' moduna çeker.
    """
    if not verify_admin(request):
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
            success = db.update_property_status(clean_id, "inactive")
        elif hasattr(db, 'update_property_in_db'):
            success = db.update_property_in_db(clean_id, {"status": "inactive"})
        else:
            # 2. Öncelik (Yedek): Fonksiyonlar yoksa doğrudan SQL ile veritabanını güncelle
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("UPDATE properties SET status = 'inactive' WHERE id = %s", (clean_id,))
            conn.commit()
            success = cur.rowcount > 0

        if success:
            return {"success": True, "message": "Property successfully changed to inactive mode."}
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
    if not verify_admin(request):
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
async def admin_quick_approve_property(property_id: int, request: Request):
    """Approving sayfasındaki butonlar için hızlı onaylama (status -> 'active') endpoint'i"""
    if not verify_admin(request):
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
async def admin_quick_reject_property(property_id: int, request: Request):
    """Approving sayfasındaki butonlar için hızlı reddetme (status -> 'inactive') endpoint'i"""
    if not verify_admin(request):
        return JSONResponse(status_code=403, content={"success": False, "message": "Yetkisiz erişim: Admin değilsiniz."})
    
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE properties SET status = 'inactive' WHERE id = %s",
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
        "description": description, "image": image_urls_list[0], "status": "pending"
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
        # --- YETKİ KONTROLÜ: Sadece admin veya ilanın sahibi agent güncelleyebilir ---
        current_user = db.get_user_from_request(request)
        if not current_user:
            return JSONResponse(status_code=401, content={"error": "Bu işlem için giriş yapmalısınız."})
        if not db.can_user_modify_property(current_user, property_id):
            return JSONResponse(status_code=403, content={"error": "Bu ilanı düzenleme yetkiniz yok."})
        user_role = current_user.get("role", "guest")

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
        cur.execute("SELECT * FROM properties WHERE LOWER(TRIM(status)) IN ('pending', 'approving') ORDER BY id DESC")
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