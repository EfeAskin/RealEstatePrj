from fastapi import APIRouter, Request, Query, Depends, HTTPException, WebSocket, WebSocketDisconnect, Form
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.concurrency import run_in_threadpool  # Senkron DB işlemlerini asenkrona uydurmak için
import database as db
from typing import List, Dict, Optional, Union
import datetime
import json

router = APIRouter()

# --- WEB SOCKET BAĞLANTI YÖNETİCİSİ (ODA BAZLI) ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, room_id: str, websocket: WebSocket):
        # NOT: accept() işlemi ana endpoint içinde kontrollü yapıldığı için burada tekrar accept çağrılmıyor.
        if room_id not in self.active_connections:
            self.active_connections[room_id] = []
        if websocket not in self.active_connections[room_id]:
            self.active_connections[room_id].append(websocket)

    def disconnect(self, room_id: str, websocket: WebSocket):
        if room_id in self.active_connections:
            if websocket in self.active_connections[room_id]:
                self.active_connections[room_id].remove(websocket)
            if not self.active_connections[room_id]:
                del self.active_connections[room_id]

    async def broadcast_to_room(self, room_id: str, message: dict):
        if room_id in self.active_connections:
            for connection in list(self.active_connections[room_id]):
                try:
                    await connection.send_json(message)
                except Exception:
                    self.disconnect(room_id, connection)

manager = ConnectionManager()

# --- COOKIE GÜVENLİK KULLANICI DOĞRULAMA FONKSiyonu ---
def get_current_user_from_cookie(request: Union[Request, WebSocket]) -> Optional[dict]:
    try:
        user_id_cookie = request.cookies.get("user_id")
    except AttributeError:
        return None
        
    if not user_id_cookie:
        return None
    return db.get_user_from_cookie(user_id_cookie)

# --- WS ODA YETKİ KONTROLÜ VE DB YAZMA FONKSİYONLARI (THREAD-SAFE) ---
def verify_room_access(room_id: int, user_id: int) -> bool:
    """Kullanıcının bu odaya erişim yetkisi var mı kontrol eder (Senkron DB fonksiyonu)"""
    conn = db.get_db_connection()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 1 FROM chat_rooms 
            WHERE id = %s AND (user_id = %s OR agent_id = %s) AND is_ai_chat = FALSE
        """, (room_id, user_id, user_id))
        allowed = cur.fetchone() is not None
        cur.close()
        conn.close()
        return allowed
    except Exception as e:
        print(f"Oda yetki kontrolü hatası: {e}")
        if conn: conn.close()
        return False

def save_ws_message_to_db(room_id: int, sender_id: int, message_text: str):
    """WebSocket'ten gelen mesajı arka planda DB'ye kaydeder (Senkron DB fonksiyonu)"""
    conn = db.get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO chat_messages (room_id, sender_id, message_text, is_from_ai, is_read, created_at) 
                VALUES (%s, %s, %s, FALSE, FALSE, NOW() AT TIME ZONE 'UTC')
            """, (room_id, sender_id, message_text.strip()))
            conn.commit()
            cur.close()
            conn.close()
            print(f"Mesaj başarıyla Neon DB'ye yazıldı. Oda: {room_id}, Gönderen: {sender_id}")
        except Exception as db_err:
            print("WS DB Save Error:", str(db_err))
            if conn:
                conn.rollback()
                conn.close()

# --- ESNEK VE TAM DONANIMLI SAYFA ROTA ENTEGRASYONU ---
@router.get("/profile/messages")
async def get_messages_page_safe(request: Request, chat_id: Optional[str] = None):
    current_user = get_current_user_from_cookie(request)
    if not current_user:
        current_user = getattr(db, 'current_user_data', None)
        
    if not current_user:
        return RedirectResponse(url="/auth/login?error=Yeniden giris yapiniz.")

    user_id = int(current_user.get("id"))

    clean_chat_id = None
    if chat_id and chat_id.strip() and chat_id != "undefined" and chat_id != "None":
        try:
            clean_chat_id = int(chat_id)
        except ValueError:
            clean_chat_id = None

    conversations = []
    messages = []
    active_chat_partner = None
    active_property = None
    unread_total_db = 0

    conn = db.get_db_connection()
    if conn:
        try:
            from psycopg2.extras import RealDictCursor
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # 1. SOL LİSTE: Giriş yapan kullanıcının tüm aktif odalarını çekiyoruz.
            list_query = """
                SELECT 
                    cr.id as chat_id,
                    cr.id as room_id,
                    cr.property_id,
                    p.name as property_title,
                    (CASE WHEN cr.agent_id = %s THEN u.id ELSE a.id END) as partner_id,
                    (CASE WHEN cr.agent_id = %s THEN u.first_name ELSE a.first_name END) as first_name,
                    (CASE WHEN cr.agent_id = %s THEN u.last_name ELSE a.last_name END) as last_name,
                    (CASE WHEN cr.agent_id = %s THEN u.profile_image ELSE a.profile_image END) as profile_image,
                    (SELECT message_text FROM chat_messages WHERE room_id = cr.id ORDER BY id DESC LIMIT 1) as last_message,
                    (SELECT to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') FROM chat_messages WHERE room_id = cr.id ORDER BY id DESC LIMIT 1) as last_message_time,
                    (SELECT COUNT(*) FROM chat_messages WHERE room_id = cr.id AND sender_id != %s AND is_read = FALSE) as unread_count
                FROM chat_rooms cr
                LEFT JOIN properties p ON cr.property_id = p.id
                LEFT JOIN users u ON cr.user_id = u.id
                LEFT JOIN users a ON cr.agent_id = a.id
                WHERE (cr.user_id = %s OR cr.agent_id = %s) AND cr.is_ai_chat = FALSE
                ORDER BY cr.created_at DESC
            """
            cur.execute(list_query, (user_id, user_id, user_id, user_id, user_id, user_id, user_id))
            raw_conversations = cur.fetchall()
            
            for row in raw_conversations:
                p_img = row["profile_image"]
                if not p_img or not str(p_img).strip():
                    p_img = "default_user.png"
                
                conversations.append({
                    "id": row["chat_id"], 
                    "chat_id": row["chat_id"],
                    "room_id": row["room_id"],
                    "property_id": row["property_id"],
                    "property_title": row["property_title"],
                    "partner_id": row["partner_id"],
                    "first_name": row["first_name"] if row["first_name"] else "",
                    "last_name": row["last_name"] if row["last_name"] else f"User #{row['partner_id']}",
                    "profile_image": p_img,
                    "last_message": row["last_message"] if row["last_message"] else "Henüz mesaj yok.",
                    "last_message_time": row.get("last_message_time") or "",
                    "unread_count": int(row["unread_count"]),
                    "is_online": True
                })

            # 2. SAĞ TARAF DETAYI: Sohbet odası seçildiyse mesajları ve partner detaylarını getir.
            if clean_chat_id:
                partner_query = """
                    SELECT 
                        cr.id,
                        cr.property_id,
                        (CASE WHEN cr.agent_id = %s THEN u.id ELSE a.id END) as partner_id,
                        (CASE WHEN cr.agent_id = %s THEN u.first_name ELSE a.first_name END) as first_name,
                        (CASE WHEN cr.agent_id = %s THEN u.last_name ELSE a.last_name END) as last_name,
                        (CASE WHEN cr.agent_id = %s THEN u.profile_image ELSE a.profile_image END) as profile_image,
                        (CASE WHEN cr.agent_id = %s THEN u.role ELSE a.role END) as role
                    FROM chat_rooms cr
                    LEFT JOIN users u ON cr.user_id = u.id
                    LEFT JOIN users a ON cr.agent_id = a.id
                    WHERE cr.id = %s AND (cr.user_id = %s OR cr.agent_id = %s)
                """
                cur.execute(partner_query, (user_id, user_id, user_id, user_id, user_id, clean_chat_id, user_id, user_id))
                raw_partner = cur.fetchone()
                
                if raw_partner:
                    p_img = raw_partner["profile_image"]
                    if not p_img or not str(p_img).strip():
                        p_img = "default_user.png"
                        
                    active_chat_partner = {
                        "id": raw_partner["partner_id"],
                        "first_name": raw_partner["first_name"] if raw_partner["first_name"] else "User",
                        "last_name": raw_partner["last_name"] if raw_partner["last_name"] else f"#{raw_partner['partner_id']}",
                        "profile_image": p_img,
                        "role": raw_partner["role"] if raw_partner["role"] else "User"
                    }

                    cur.execute("SELECT id, name, price_normalized FROM properties WHERE id = %s", (raw_partner.get("property_id"),))
                    prop_row = cur.fetchone()
                    if prop_row:
                        active_property = {
                            "name": prop_row["name"],
                            "price": f"{prop_row['price_normalized']:,} TL" if isinstance(prop_row['price_normalized'], (int, float)) else prop_row['price_normalized']
                        }

                    # Mesaj geçmişini çekiyoruz
                    cur.execute("""
                        SELECT id, room_id, sender_id, message_text, is_read,
                               to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') as created_at_iso
                        FROM chat_messages
                        WHERE room_id = %s
                        ORDER BY id ASC
                    """, (clean_chat_id,))
                    active_messages = cur.fetchall()
                    
                    for m in active_messages:
                        messages.append({
                            "id": m["id"],
                            "room_id": m["room_id"],
                            "sender_id": m["sender_id"],
                            "message_text": m["message_text"],
                            "is_read": m["is_read"],
                            "created_at": m["created_at_iso"]
                        })

                    # Mevcut odaya girildiği için okunmamış mesajları okundu olarak işaretle
                    cur.execute("""
                        UPDATE chat_messages SET is_read = TRUE 
                        WHERE room_id = %s AND sender_id != %s
                    """, (clean_chat_id, user_id))
                    conn.commit()

            # --- JINJA SÜRECİNİ BESLEMEK İÇİN GÜNCEL TOPLAM OKUNMAMIŞ SAYISINI SORGULA ---
            cur.execute("""
                SELECT COUNT(*) FROM chat_messages cm
                JOIN chat_rooms cr ON cm.room_id = cr.id
                WHERE (cr.user_id = %s OR cr.agent_id = %s)
                  AND cm.sender_id != %s 
                  AND cm.is_read = FALSE
                  AND cr.is_ai_chat = FALSE
            """, (user_id, user_id, user_id))
            unread_total_db = cur.fetchone()[0]

            cur.close()
            conn.close()
        except Exception as e:
            print("Chat Sayfası SQL Hatası: ", str(e))
            if conn:
                conn.close()
            unread_total_db = 0
    else:
        unread_total_db = 0

    from backend import templates
    return templates.TemplateResponse("messages.html", {
        "request": request,
        "conversations": conversations,
        "messages": messages,
        "active_chat_partner": active_chat_partner,
        "active_property": active_property,
        "active_conversation_id": clean_chat_id,
        "current_user_id": user_id,
        "unread_messages_count": unread_total_db
    })

# --- REST API: HTTP POST İLE MESAJ GÖNDERME (Sadece Yedek Akış) ---
@router.post("/profile/messages/send")
async def send_message_via_form(
    request: Request,
    chat_id: int = Form(...),
    message_text: str = Form(...),
    receiver_id: Optional[str] = Form(None)
):
    current_user = get_current_user_from_cookie(request)
    if not current_user:
        current_user = getattr(db, 'current_user_data', None)
        
    if not current_user:
        return JSONResponse(status_code=401, content={"success": False, "error": "Yetkisiz işlem."})

    sender_id = int(current_user.get("id"))

    if not chat_id or not message_text.strip():
        return JSONResponse(status_code=400, content={"success": False, "error": "Mesaj boş olamaz."})

    conn = db.get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM chat_rooms WHERE id = %s AND (user_id = %s OR agent_id = %s)", (chat_id, sender_id, sender_id))
            if not cur.fetchone():
                cur.close()
                conn.close()
                return JSONResponse(status_code=403, content={"success": False, "error": "Bu odaya mesaj gönderme yetkiniz yok."})

            cur.execute("""
                INSERT INTO chat_messages (room_id, sender_id, message_text, is_from_ai, is_read, created_at) 
                VALUES (%s, %s, %s, FALSE, FALSE, NOW() AT TIME ZONE 'UTC')
            """, (chat_id, sender_id, message_text.strip()))
            conn.commit()
            cur.close()
            conn.close()
            return JSONResponse(content={"success": True})
        except Exception as e:
            print("Mesaj Gönderim Hatası: ", str(e))
            if conn: 
                conn.rollback()
                conn.close()
            return JSONResponse(status_code=500, content={"success": False, "error": str(e)})

    return JSONResponse(status_code=500, content={"success": False, "error": "Veritabanı bağlantısı yok."})

# --- İLAN DETAYDAN SOHBET BAŞLATMA ---
@router.post("/chat/initiate/{property_id}")
async def initiate_chat(property_id: int, request: Request):
    current_user = get_current_user_from_cookie(request)
    if not current_user:
        current_user = getattr(db, 'current_user_data', None)
        
    if not current_user:
        return JSONResponse(status_code=401, content={"error": "Mesajlaşmak için giriş yapmalısınız."})
    
    user_id = int(current_user.get("id"))
    conn = db.get_db_connection()
    if not conn:
        return JSONResponse(status_code=500, content={"error": "Veritabanı bağlantı hatası."})
        
    try:
        from psycopg2.extras import RealDictCursor
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("SELECT id, name, agent_id FROM properties WHERE id = %s", (property_id,))
        prop = cur.fetchone()
        if not prop:
            cur.close()
            conn.close()
            return JSONResponse(status_code=404, content={"error": "İlan bulunamadı."})
            
        agent_id = int(prop.get("agent_id"))
        if user_id == agent_id:
            cur.close()
            conn.close()
            return JSONResponse(status_code=400, content={"error": "Kendi ilanınız için sohbet başlatamazsınız."})

        prop_name = prop.get("name") if prop.get("name") else "İlan"

        cur.execute("""
            SELECT id FROM chat_rooms 
            WHERE property_id = %s AND user_id = %s AND agent_id = %s AND is_ai_chat = FALSE
        """, (property_id, user_id, agent_id))
        room = cur.fetchone()
        
        welcome_text = f"Merhaba, '{prop_name}' ilanınızla ilgileniyorum. Detaylı bilgi alabilir miyim?"
        
        if room:
            room_id = room["id"]
            cur.execute("""
                INSERT INTO chat_messages (room_id, sender_id, message_text, is_from_ai, is_read, created_at) 
                VALUES (%s, %s, %s, FALSE, FALSE, NOW() AT TIME ZONE 'UTC') RETURNING id
            """, (room_id, user_id, welcome_text))
            conn.commit()
            
            payload = {
                "room_id": room_id,
                "sender_id": int(user_id),
                "message": welcome_text,
                "message_text": welcome_text,
                "is_read": False
            }
            await manager.broadcast_to_room(str(room_id), payload)
        else:
            cur.execute("""
                INSERT INTO chat_rooms (property_id, user_id, agent_id, is_ai_chat, created_at) 
                VALUES (%s, %s, %s, FALSE, NOW() AT TIME ZONE 'UTC') RETURNING id
            """, (property_id, user_id, agent_id))
            room_id = cur.fetchone()["id"]
            
            cur.execute("""
                INSERT INTO chat_messages (room_id, sender_id, message_text, is_from_ai, is_read, created_at) 
                VALUES (%s, %s, %s, FALSE, FALSE, NOW() AT TIME ZONE 'UTC')
            """, (room_id, user_id, welcome_text))
            conn.commit()
            
        cur.close()
        conn.close()
        
        return {"status": "success", "room_id": room_id, "agent_id": agent_id, "name": prop_name, "title": prop_name}
    except Exception as e:
        if conn: 
            conn.rollback()
            conn.close()
        return JSONResponse(status_code=500, content={"error": str(e)})

# --- PROFİL / MESSAGES SAYFASI (SOL LİSTEYİ BESLEYEN API) ---
@router.get("/profile/messages/api")
async def get_my_chat_rooms(request: Request):
    current_user = get_current_user_from_cookie(request)
    if not current_user:
        current_user = getattr(db, 'current_user_data', None)
        
    if not current_user:
        return JSONResponse(status_code=401, content={"error": "Yetkisiz erişim."})
        
    user_id = int(current_user.get("id"))
    role = current_user.get("role", getattr(db, 'current_user_role', 'user'))
    
    conn = db.get_db_connection()
    if not conn:
        return JSONResponse(status_code=500, content={"error": "Veritabanı bağlantısı kurulamadı."})
        
    try:
        from psycopg2.extras import RealDictCursor
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        if role == 'admin':
            query = """
                SELECT cr.*, cr.id as chat_id, p.name as property_title,
                       (u.first_name || ' ' || u.last_name) as full_name, u.profile_image as profile_image,
                       (a.first_name || ' ' || a.last_name) as agent_name, a.profile_image as agent_avatar
                FROM chat_rooms cr
                LEFT JOIN properties p ON cr.property_id = p.id
                LEFT JOIN users u ON cr.user_id = u.id
                LEFT JOIN users a ON cr.agent_id = a.id
                WHERE cr.is_ai_chat = FALSE
                ORDER BY cr.created_at DESC
            """
            cur.execute(query)
            
        elif role == 'agent':
            query = """
                SELECT cr.*, cr.id as chat_id, p.name as property_title,
                       (u.first_name || ' ' || u.last_name) as full_name, 
                       u.profile_image as profile_image,
                       (SELECT COUNT(*) FROM chat_messages WHERE room_id = cr.id AND sender_id != %s AND is_read = FALSE) as unread_count
                FROM chat_rooms cr
                LEFT JOIN properties p ON cr.property_id = p.id
                LEFT JOIN users u ON cr.user_id = u.id
                WHERE cr.agent_id = %s AND cr.is_ai_chat = FALSE
                ORDER BY cr.created_at DESC
            """
            cur.execute(query, (user_id, user_id))
            
        else: 
            query = """
                SELECT cr.*, cr.id as chat_id, p.name as property_title,
                       (a.first_name || ' ' || a.last_name) as full_name, 
                       a.profile_image as profile_image,
                       (SELECT COUNT(*) FROM chat_messages WHERE room_id = cr.id AND sender_id != %s AND is_read = FALSE) as unread_count
                FROM chat_rooms cr
                LEFT JOIN properties p ON cr.property_id = p.id
                LEFT JOIN users a ON cr.agent_id = a.id
                WHERE cr.user_id = %s AND cr.is_ai_chat = FALSE
                ORDER BY cr.created_at DESC
            """
            cur.execute(query, (user_id, user_id))
            
        rooms = cur.fetchall()
        
        for r in rooms:
            p_img = r.get("profile_image")
            if p_img and str(p_img).strip():
                r["profile_image"] = f"/static/htmlfotos/{p_img}"
            else:
                r["profile_image"] = "/static/htmlfotos/default_user.png"
            if not r.get("full_name") or not r["full_name"].strip():
                r["full_name"] = "Kullanıcı"

        cur.close()
        conn.close()
        return rooms
    except Exception as e:
        if conn: 
            conn.close()
        return JSONResponse(status_code=500, content={"error": str(e)})

# --- SEÇİLEN SOHBETİN MESAJ GEÇMİŞENİ GETİRME (API) ---
@router.get("/chat/room/{room_id}/messages")
async def get_room_messages(room_id: int, request: Request):
    current_user = get_current_user_from_cookie(request)
    if not current_user:
        current_user = getattr(db, 'current_user_data', None)
         
    if not current_user:
         return JSONResponse(status_code=401, content={"error": "Giriş yapmalısınız."})
         
    user_id = int(current_user.get("id"))
    conn = db.get_db_connection()
    if not conn:
        return JSONResponse(status_code=500, content={"error": "Veritabanı bağlantısı kurulamadı."})

    try:
        from psycopg2.extras import RealDictCursor
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("SELECT 1 FROM chat_rooms WHERE id = %s AND (user_id = %s OR agent_id = %s)", (room_id, user_id, user_id))
        if not cur.fetchone():
            cur.close()
            conn.close()
            return JSONResponse(status_code=403, content={"error": "Bu odadaki mesajları görme yetkiniz yok."})

        cur.execute("""
            SELECT m.id, m.room_id, m.sender_id, m.message_text, m.is_read,
                   to_char(m.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') as created_at,
                   u.first_name, u.last_name, u.profile_image 
            FROM chat_messages m
            LEFT JOIN users u ON m.sender_id = u.id
            WHERE m.room_id = %s
            ORDER BY m.id ASC
        """, (room_id,))
        messages = cur.fetchall()
        
        for m in messages:
            p_img = m.get("profile_image")
            if p_img and str(p_img).strip():
                m["profile_image"] = f"/static/htmlfotos/{p_img}"
            else:
                m["profile_image"] = "/static/htmlfotos/default_user.png"
        
        cur.execute("""
            UPDATE chat_messages SET is_read = TRUE 
            WHERE room_id = %s AND sender_id != %s
        """, (room_id, user_id))
        
        conn.commit()
        cur.close()
        conn.close()
        return messages
    except Exception as e:
        if conn: 
            conn.close()
        return JSONResponse(status_code=500, content={"error": str(e)})

# --- TOPLAM OKUNMAMIŞ MESAJ KONTROLÜ ---
@router.get("/chat/unread-check")
async def unread_check(request: Request):
    current_user = get_current_user_from_cookie(request)
    if not current_user:
        current_user = getattr(db, 'current_user_data', None)
        
    if not current_user:
        return {"unread_total": 0}
        
    user_id = int(current_user.get("id"))
    conn = db.get_db_connection()
    if not conn:
        return {"unread_total": 0}
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM chat_messages cm
            JOIN chat_rooms cr ON cm.room_id = cr.id
            WHERE (cr.user_id = %s OR cr.agent_id = %s)
              AND cm.sender_id != %s 
              AND cm.is_read = FALSE
              AND cr.is_ai_chat = FALSE
        """, (user_id, user_id, user_id))
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        return {"unread_total": count}
    except:
        if conn: 
            conn.close()
        return {"unread_total": 0}

# --- GERÇEK ZAMANLI GÜVENLİ WEBSOCKET SİSTEMİ (LIFECYCLE-SAFE) ---
@router.websocket("/ws/chat/{room_id}")
async def websocket_chat_endpoint(websocket: WebSocket, room_id: str):
    current_user = get_current_user_from_cookie(websocket)
    if not current_user:
        current_user = getattr(db, 'current_user_data', None)
        
    if not current_user:
        await websocket.close(code=4001)
        return

    user_id = int(current_user.get("id"))
    
    # YAŞAM DÖNGÜSÜ DÜZELTMESİ: accept() fonksiyonunu bir kez çağırıyoruz.
    await websocket.accept()
    
    # İlk el sıkışmada URL'den gelen odayı manager havuzuna hemen kaydedelim.
    current_room_str = str(room_id)
    await manager.connect(current_room_str, websocket)
    
    try:
        while True:
            raw_data = await websocket.receive_text()
            data = json.loads(raw_data)
            
            # Mini kutucuktan dinamik oda bilgisi değişirse veya eklenirse yakala
            target_room = data.get("room_id", room_id)
            try:
                clean_room_id = int(target_room)
            except (ValueError, TypeError):
                continue

            # Odalar arası geçiş senaryosunu veya ilk bağlantının doğruluğunu güvenceye al
            if str(clean_room_id) != current_room_str:
                manager.disconnect(current_room_str, websocket)
                current_room_str = str(clean_room_id)
                await manager.connect(current_room_str, websocket)

            # Yetki kontrolü (Threadpool içinde senkron bloke etmeyi kırar)
            is_allowed = await run_in_threadpool(verify_room_access, clean_room_id, user_id)
            if not is_allowed:
                continue

            # Payload okuma ('message' veya 'message_text')
            message_text = data.get("message_text") or data.get("message")
            if not message_text or not str(message_text).strip():
                continue

            # KRİTİK DÜZELTME: Veritabanına kayıt işlemi artık kesinlikle çalışacak ve kilitlenme yaratmayacak
            await run_in_threadpool(save_ws_message_to_db, clean_room_id, user_id, message_text)

            # İstemciler için temiz ISO UTC zaman damgası
            now_iso = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            
            payload = {
                "room_id": clean_room_id,
                "sender_id": user_id,
                "message": message_text.strip(),
                "message_text": message_text.strip(),
                "is_read": False,
                "created_at": now_iso
            }
            
            # Odaya bağlı olan herkese (ve mini kutucuğa) mesajı dağıt
            await manager.broadcast_to_room(current_room_str, payload)
                
    except WebSocketDisconnect:
        manager.disconnect(current_room_str, websocket)
    except Exception as e:
        print("WebSocket İç Döngü Hatası:", str(e))
        manager.disconnect(current_room_str, websocket)