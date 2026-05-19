from fastapi import APIRouter, Request, Query, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
import database as db
from typing import List, Dict
import datetime

router = APIRouter()

# --- WEB SOCKET BAĞLANTI YÖNETİCİSİ ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, user_id: str, websocket: WebSocket):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)

    def disconnect(self, user_id: str, websocket: WebSocket):
        if user_id in self.active_connections:
            if websocket in self.active_connections[user_id]:
                self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]

    async def send_personal_message(self, message: dict, user_id: str):
        if user_id in self.active_connections:
            for connection in self.active_connections[user_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    pass

manager = ConnectionManager()

# --- 1. İLAN DETAYDAN SOHBET BAŞLATMA (Pop-up açıldığında) ---
@router.post("/chat/initiate/{property_id}")
async def initiate_chat(property_id: int):
    current_user = getattr(db, 'current_user_data', None)
    if not current_user:
        return JSONResponse(status_code=401, content={"error": "Mesajlaşmak için giriş yapmalısınız."})
    
    user_id = current_user.get("id")
    conn = db.get_db_connection()
    if not conn:
        return JSONResponse(status_code=500, content={"error": "Veritabanı bağlantı hatası."})
        
    try:
        from psycopg2.extras import RealDictCursor
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # İlanı ve ilanın emlakçısını bulalım
        cur.execute("SELECT id, name, agent_id FROM properties WHERE id = %s", (property_id,))
        prop = cur.fetchone()
        if not prop:
            return JSONResponse(status_code=404, content={"error": "İlan bulunamadı."})
            
        agent_id = prop.get("agent_id")
        if user_id == agent_id:
            return JSONResponse(status_code=400, content={"error": "Kendi ilanınız için sohbet başlatamazsınız."})

        # Mevcut oda var mı?
        cur.execute("""
            SELECT id FROM chat_rooms 
            WHERE property_id = %s AND user_id = %s AND agent_id = %s
        """, (property_id, user_id, agent_id))
        room = cur.fetchone()
        
        if room:
            room_id = room["id"]
        else:
            # Yeni oda oluştur
            cur.execute("""
                INSERT INTO chat_rooms (property_id, user_id, agent_id) 
                VALUES (%s, %s, %s) RETURNING id
            """, (property_id, user_id, agent_id))
            room_id = cur.fetchone()["id"]
            
            # WhatsApp tarzı ilk otomatik mesajı fırlat
            welcome_text = f"Merhaba, '{prop['name']}' ilanınızla ilgileniyorum. Detaylı bilgi alabilir miyim?"
            cur.execute("""
                INSERT INTO chat_messages (room_id, sender_id, message_text, is_read) 
                VALUES (%s, %s, %s, FALSE)
            """, (room_id, user_id, welcome_text))
            
        conn.commit()
        cur.close()
        conn.close()
        
        return {"status": "success", "room_id": room_id}
    except Exception as e:
        if conn: conn.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})

# --- 2. PROFİL / MESSAGES SAYFASI (SOL LİSTEYİ BESLEYEN API) ---
@router.get("/profile/messages/api")
async def get_my_chat_rooms():
    current_user = getattr(db, 'current_user_data', None)
    if not current_user:
        return JSONResponse(status_code=401, content={"error": "Yetkisiz erişim."})
        
    user_id = current_user.get("id")
    role = db.current_user_role # 'user', 'agent' veya 'admin'
    
    conn = db.get_db_connection()
    try:
        from psycopg2.extras import RealDictCursor
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # --- ADMIN GÖRÜNÜMÜ (Tüm odaları kim kiminle konuşuyor döküman gibi listeler) ---
        if role == 'admin':
            query = """
                SELECT cr.*, p.name as property_title, p.image_path as property_image,
                       u.first_name as user_first, u.last_name as user_last, u.profile_image as user_avatar,
                       a.first_name as agent_first, a.last_name as agent_last, a.profile_image as agent_avatar, a.company_name
                FROM chat_rooms cr
                LEFT JOIN properties p ON cr.property_id = p.id
                LEFT JOIN users u ON cr.user_id = u.id
                LEFT JOIN users a ON cr.agent_id = a.id
                ORDER BY cr.created_at DESC
            """
            cur.execute(query)
            
        # --- AGENT GÖRÜNÜMÜ (Müşterilerin bilgilerini ve okunmamış sayılarını getirir) ---
        elif role == 'agent':
            query = """
                SELECT cr.*, p.name as property_title, p.image_path as property_image,
                       u.first_name as counterpart_first, u.last_name as counterpart_last, 
                       u.profile_image as counterpart_avatar, u.company_name as counterpart_company,
                       (SELECT COUNT(*) FROM chat_messages WHERE room_id = cr.id AND sender_id != %s AND is_read = FALSE) as unread_count
                FROM chat_rooms cr
                LEFT JOIN properties p ON cr.property_id = p.id
                LEFT JOIN users u ON cr.user_id = u.id
                WHERE cr.agent_id = %s
                ORDER BY cr.created_at DESC
            """
            cur.execute(query, (user_id, user_id))
            
        # --- USER GÖRÜNÜMÜ (Konuştuğu Emlakçıların PP, İsim ve Şirket Adlarını getirir) ---
        else: 
            query = """
                SELECT cr.*, p.name as property_title, p.image_path as property_image,
                       a.first_name as counterpart_first, a.last_name as counterpart_last, 
                       a.profile_image as counterpart_avatar, a.company_name as counterpart_company,
                       (SELECT COUNT(*) FROM chat_messages WHERE room_id = cr.id AND sender_id != %s AND is_read = FALSE) as unread_count
                FROM chat_rooms cr
                LEFT JOIN properties p ON cr.property_id = p.id
                LEFT JOIN users a ON cr.agent_id = a.id
                WHERE cr.user_id = %s
                ORDER BY cr.created_at DESC
            """
            cur.execute(query, (user_id, user_id))
            
        rooms = cur.fetchall()
        cur.close()
        conn.close()
        return rooms
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# --- 3. SEÇİLEN SOHBETİN MESAJ GEÇMİŞİNİ GETİRME (SAĞ TARAF) ---
@router.get("/chat/room/{room_id}/messages")
async def get_room_messages(room_id: int):
    current_user = getattr(db, 'current_user_data', None)
    if not current_user:
         return JSONResponse(status_code=401, content={"error": "Giriş yapmalısınız."})
         
    user_id = current_user.get("id")
    conn = db.get_db_connection()
    try:
        from psycopg2.extras import RealDictCursor
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Mesaj geçmişini kronolojik çek
        cur.execute("""
            SELECT m.*, u.first_name, u.last_name, u.profile_image 
            FROM chat_messages m
            LEFT JOIN users u ON m.sender_id = u.id
            WHERE m.room_id = %s
            ORDER BY m.created_at ASC
        """, (room_id,))
        messages = cur.fetchall()
        
        # Odaya girildiği an karşı taraftan gelen okunmamış tüm mesajları "Okundu" yap!
        cur.execute("""
            UPDATE chat_messages SET is_read = TRUE 
            WHERE room_id = %s AND sender_id != %s
        """, (room_id, user_id))
        
        conn.commit()
        cur.close()
        conn.close()
        return messages
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# --- 4. TOPLAM OKUNMAMIŞ MESAJ KONTROLÜ (NAVBAR / PROFIL KANALI KAN KIRMIZI NOKTA İÇİN) ---
@router.get("/chat/unread-check")
async def unread_check():
    current_user = getattr(db, 'current_user_data', None)
    if not current_user:
        return {"unread_total": 0}
        
    user_id = current_user.get("id")
    conn = db.get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM chat_messages cm
            JOIN chat_rooms cr ON cm.room_id = cr.id
            WHERE (cr.user_id = %s OR cr.agent_id = %s)
              AND cm.sender_id != %s 
              AND cm.is_read = FALSE
        """, (user_id, user_id, user_id))
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        return {"unread_total": count}
    except:
        return {"unread_total": 0}

# --- 5. GERÇEK ZAMANLI WEBSOCKET SİSTEMİ ---
@router.websocket("/ws/chat/{user_id}")
async def websocket_chat_endpoint(websocket: WebSocket, user_id: str):
    await manager.connect(user_id, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            room_id = data.get("room_id")
            sender_id = int(user_id)
            message_text = data.get("message_text")
            receiver_id = data.get("receiver_id")
            
            conn = db.get_db_connection()
            if conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO chat_messages (room_id, sender_id, message_text) 
                    VALUES (%s, %s, %s) RETURNING id, created_at
                """, (room_id, sender_id, message_text))
                res = cur.fetchone()
                conn.commit()
                cur.close()
                conn.close()
                
                payload = {
                    "room_id": room_id,
                    "sender_id": sender_id,
                    "message_text": message_text,
                    "created_at": str(res[1]) if res else str(datetime.datetime.now())
                }
                
                # İki tarafın ekranına da pıt diye veriyi düşür (Sayfa yenilemeye son!)
                await manager.send_personal_message(payload, str(sender_id))
                await manager.send_personal_message(payload, str(receiver_id))
                
    except WebSocketDisconnect:
        manager.disconnect(user_id, websocket)