import os
from fastapi import APIRouter, Request, Form, HTTPException, Body, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime
import database as db  # Projenizin merkezi DB modülü
from psycopg2.extras import RealDictCursor

router = APIRouter(prefix="/tickets", tags=["Tickets"])

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# =========================================================================
# 1. YENİ BİLET OLUŞTURMA (ABOUT.HTML FORM ALANLARI İLE %100 UYUMLU VE GÜVENLİ)
# =========================================================================
@router.post("/create")
async def create_ticket(
    request: Request,
    subject: str = Form(...),
    message: str = Form(...),  # about.html içerisindeki detaylı mesaj alanı
    ticket_type: str = Form(...)
):
    current_user = getattr(request.state, "user", None)
    if not current_user:
        return RedirectResponse(url="/login/user", status_code=status.HTTP_303_SEE_OTHER)
        
    user_id = current_user.get("id")
    
    if not subject.strip():
        raise HTTPException(status_code=400, detail="Bilet konusu boş olamaz.")
    if not message.strip():
        raise HTTPException(status_code=400, detail="Bilet mesaj içeriği boş olamaz.")
        
    valid_types = ['Support', 'Bugs', 'Complaints', 'Desire', 'Others']
    formatted_type = ticket_type.strip().capitalize()
    if formatted_type not in valid_types:
        formatted_type = 'Others'
        
    conn = db.get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # Konuyu (Subject) biletin başlığı olarak kaydediyoruz
        cursor.execute("""
            INSERT INTO tickets (sender_id, subject, ticket_type, ticket_status, created_at, updated_at)
            VALUES (%s, %s, %s, 'Waiting', NOW(), NOW())
            RETURNING id
        """, (user_id, subject.strip()[:80], formatted_type))
        
        new_ticket = cursor.fetchone()
        ticket_id = new_ticket['id']
        
        # Detaylı mesaj metnini (Message) biletin İLK mesajı olarak mesajlar tablosuna yazıyoruz
        cursor.execute("""
            INSERT INTO ticket_messages (ticket_id, sender_id, message_text, sent_at)
            VALUES (%s, %s, %s, NOW())
        """, (ticket_id, user_id, message.strip()))
        
        conn.commit()
        return RedirectResponse(url=f"/tickets/room/{ticket_id}", status_code=status.HTTP_303_SEE_OTHER)
        
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Bilet oluşturulurken hata: {str(e)}")
    finally:
        cursor.close()
        conn.close()

# =========================================================================
# 1.5 KİŞİSEL BİLETLERİ LİSTELEME VE GİRİŞ NOKTASI (AGENT GÜVENLİK FİLTRELİ)
# =========================================================================
@router.get("/my-tickets", response_class=HTMLResponse)
async def get_my_tickets_list(request: Request):
    current_user = getattr(request.state, "user", None)
    if not current_user:
        user_role = request.cookies.get("user_role", "user")
        return RedirectResponse(url=f"/login/{user_role}", status_code=303)
        
    user_id = current_user.get("id")
    user_role = (current_user.get("role") or "user").lower()
    
    # Sadece en üst düzey 'admin' tüm bilet havuzunu görebilir. 
    # Agent'lar da tıpkı standart kullanıcılar (user) gibi sadece kendi taleplerini görecek.
    is_absolute_admin = (user_role == "admin")
    
    conn = db.get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        if is_absolute_admin:
            cursor.execute("""
                SELECT t.*, u.first_name, u.last_name, u.profile_image 
                FROM tickets t
                JOIN users u ON t.sender_id = u.id
                ORDER BY t.updated_at DESC
            """)
        else:
            # Agent ve User rollerinin tamamı sadece kendi açtığı biletleri görür!
            # Eski sorgu yerine bunu yapıştırın:
            cursor.execute("""
                SELECT t.*, u.first_name, u.last_name, u.profile_image,
                    ROW_NUMBER() OVER (PARTITION BY t.sender_id ORDER BY t.created_at ASC) as user_ticket_no
                FROM tickets t
                JOIN users u ON t.sender_id = u.id
                WHERE t.sender_id = %s
                ORDER BY t.updated_at DESC
            """, (user_id,))
            
        sidebar_tickets = cursor.fetchall()
        
    finally:
        cursor.close()
        conn.close()
        
    # Kullanıcı deneyimi için: Eğer aktif/eski biletleri varsa en güncel olanına direkt yönlendir
    if sidebar_tickets:
        first_ticket_id = sidebar_tickets[0]['id']
        return RedirectResponse(url=f"/tickets/room/{first_ticket_id}", status_code=303)
        
    # Eğer Yakup'un veya kullanıcının hiç bileti yoksa ekran tertemiz, sıfır biletle hatasız açılır
    current_profile_image = current_user.get("profile_image") if current_user.get("profile_image") else "default_user.png"
    
    return templates.TemplateResponse(request, "ticket_room.html", {
        "user": current_user,
        "role": user_role,
        "current_user_role": user_role,
        "is_admin": is_absolute_admin,
        "first_name": current_user.get("first_name", ""),
        "last_name": current_user.get("last_name", ""),
        "profile_image": current_profile_image,
        "ticket": {
            "id": 0, 
            "subject": "Henüz oluşturulmuş bir destek talebiniz yok", 
            "category": "Genel", 
            "ticket_status": "closed", 
            "owner_name": f"{current_user.get('first_name','')} {current_user.get('last_name','')}", 
            "created_at": ""
        },
        "sidebar_tickets": [],  # Hiç ticket yoksa liste tamamen boş kalır
        "messages": [],
        "p_page": "my-tickets"
    })

# =========================================================================
# 2. BİLET ODASI / CHAT EKRANI (GET) - KESİN ERİŞİM KONTROLÜ VE YALITIM
# =========================================================================
@router.get("/room/{ticket_id}", response_class=HTMLResponse)
async def get_ticket_room(ticket_id: int, request: Request):
    current_user = getattr(request.state, "user", None)
    if not current_user:
        user_role = request.cookies.get("user_role", "user")
        return RedirectResponse(url=f"/login/{user_role}", status_code=303)
        
    user_id = current_user.get("id")
    user_role = (current_user.get("role") or "user").lower()
    
    # Sadece tam yetkili admin tüm odalara serbestçe sızabilir/görebilir.
    is_absolute_admin = (user_role == "admin")
    
    conn = db.get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        if is_absolute_admin:
            cursor.execute("""
                SELECT t.*, u.first_name, u.last_name, u.profile_image 
                FROM tickets t
                JOIN users u ON t.sender_id = u.id
                WHERE t.id = %s
            """, (ticket_id,))
        else:
            # Agent ve Standart kullanıcılar yalnızca kendilerine ait ID'li bilet odasına erişebilir!
            cursor.execute("""
                SELECT t.*, u.first_name, u.last_name, u.profile_image,
                    (SELECT COUNT(*) FROM tickets WHERE sender_id = t.sender_id AND created_at <= t.created_at) as user_ticket_no
                FROM tickets t
                JOIN users u ON t.sender_id = u.id
                WHERE t.id = %s AND t.sender_id = %s
            """, (ticket_id, user_id))
            
        ticket = cursor.fetchone()
        
        # Eğer bilet bulunamadıysa ya da yetkisi yoksa doğrudan güvenli listeye atıyoruz
        if not ticket:
            return RedirectResponse(url="/tickets/my-tickets", status_code=303)
            
        # Sol Sidebar Listesi için filtreleme:
        if is_absolute_admin:
            cursor.execute("""
                SELECT t.id, t.subject, t.ticket_type, t.ticket_status, t.created_at 
                FROM tickets t
                ORDER BY t.created_at DESC
            """)
        else:
            # Odaya giren kişi agent veya user ise sol tarafta da sadece KENDİ biletlerini görür.
            # Kullanıcının kendi biletlerini, bilet sıra numarasını ve biletin son mesajını çekiyoruz
            cursor.execute("""
                SELECT t.id, t.subject, t.ticket_type, t.ticket_status, t.created_at,
                       ROW_NUMBER() OVER (PARTITION BY t.sender_id ORDER BY t.created_at ASC) as user_ticket_no,
                       CASE 
                           WHEN LENGTH(lm.message_text) > 35 THEN LEFT(lm.message_text, 35) || '...'
                           ELSE lm.message_text 
                       END as last_message_preview
                FROM tickets t
                LEFT JOIN LATERAL (
                    SELECT message_text FROM ticket_messages 
                    WHERE ticket_id = t.id 
                    ORDER BY sent_at DESC LIMIT 1
                ) lm ON TRUE
                WHERE t.sender_id = %s
                ORDER BY t.created_at DESC
            """, (user_id,))
        sidebar_tickets = cursor.fetchall()
        
        # Odaya ait mesaj geçmişini çekiyoruz
        cursor.execute("""
            SELECT tm.*, u.first_name, u.last_name, u.profile_image, u.role
            FROM ticket_messages tm
            JOIN users u ON tm.sender_id = u.id
            WHERE tm.ticket_id = %s
            ORDER BY tm.sent_at ASC
        """, (ticket_id,))
        messages_raw = cursor.fetchall()
        
        messages = []
        for msg in messages_raw:
            msg_role = (msg['role'] or 'user').lower()
            # Eğer yanıtlayan kişi admin ise veya bilet sahibi olmayan bir agent ise 'staff_reply' sayılır
            is_staff_reply = msg_role in ['admin', 'agent'] and msg['sender_id'] != ticket['sender_id']
            
            messages.append({
                "is_staff_reply": is_staff_reply,
                "sender_image": msg['profile_image'] if msg['profile_image'] else "default_user.png",
                "message": msg['message_text'],
                "sender_name": f"{msg['first_name']} {msg['last_name']}",
                "time": msg['sent_at'].strftime("%H:%M") if msg['sent_at'] else ""
            })
            
        ticket_detail = {
            "id": ticket['id'],
            "user_ticket_no": ticket['user_ticket_no'],
            "subject": ticket['subject'],
            "category": ticket['ticket_type'],
            "ticket_status": ticket['ticket_status'] if ticket['ticket_status'] else "Waiting",
            "owner_name": f"{ticket['first_name']} {ticket['last_name']}",
            "created_at": ticket['created_at'].strftime("%Y-%m-%d %H:%M") if ticket['created_at'] else ""
        }
        
        current_profile_image = current_user.get("profile_image") if current_user.get("profile_image") else "default_user.png"
        
    finally:
        cursor.close()
        conn.close()
        
    return templates.TemplateResponse(request, "ticket_room.html", {
        "user": current_user,
        "role": user_role,
        "current_user_role": user_role,
        "is_admin": is_absolute_admin,
        "first_name": current_user.get("first_name", ""),
        "last_name": current_user.get("last_name", ""),
        "profile_image": current_profile_image,
        "ticket": ticket_detail,
        "sidebar_tickets": sidebar_tickets,
        "messages": messages,
        "p_page": "my-tickets"
    })

# =========================================================================
# 3. ODAYA ANLIK MESAJ GÖNDERME API'Sİ (GÜVENLİK KONTROLLÜ)
# =========================================================================
@router.post("/room/{ticket_id}/messages")
async def send_room_message(ticket_id: int, request: Request, payload: dict = Body(...)):
    message_text = payload.get("message")
    if not message_text or not message_text.strip():
        raise HTTPException(status_code=400, detail="Mesaj boş olamaz.")
        
    current_user = getattr(request.state, "user", None)
    if not current_user:
        raise HTTPException(status_code=401, detail="Oturumunuz sonlanmış.")
        
    user_id = current_user.get("id")
    user_role = current_user.get("role", "user").lower()
    is_absolute_admin = (user_role == "admin")
    
    conn = db.get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute("SELECT sender_id, ticket_status, receiver_id FROM tickets WHERE id = %s", (ticket_id,))
        ticket = cursor.fetchone()
        if not ticket:
            raise HTTPException(status_code=404, detail="Bilet kaydı bulunamadı.")
            
        # Admin değilse ve biletin asıl sahibi değilse odaya mesaj gönderemez!
        if ticket['sender_id'] != user_id and not is_absolute_admin:
            raise HTTPException(status_code=403, detail="Bu işlem için yetkiniz yok.")
            
        cursor.execute("""
            INSERT INTO ticket_messages (ticket_id, sender_id, message_text, sent_at)
            VALUES (%s, %s, %s, NOW())
            RETURNING id
        """, (ticket_id, user_id, message_text.strip()))
        new_msg_id = cursor.fetchone()['id']
        
        # Eğer mesajı yazan admin ise bilet statüsünü güncelliyoruz
        if is_absolute_admin:
            cursor.execute("""
                UPDATE tickets 
                SET ticket_status = 'Active', 
                    receiver_id = COALESCE(receiver_id, %s),
                    updated_at = NOW()
                WHERE id = %s
            """, (user_id, ticket_id))
        else:
            if ticket['ticket_status'] in ['Success', 'Failed']:
                cursor.execute("""
                    UPDATE tickets 
                    SET ticket_status = 'Active', updated_at = NOW() 
                    WHERE id = %s
                """, (ticket_id,))
            else:
                cursor.execute("UPDATE tickets SET updated_at = NOW() WHERE id = %s", (ticket_id,))
                
        conn.commit()
        return {"status": "success", "message_id": new_msg_id}
        
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()