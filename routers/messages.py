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
templates = Jinja2Templates(directory="templates")
tr_tz = pytz.timezone("Europe/Istanbul")

@router.get("/profile/messages")
async def get_profile_messages(request: Request, chat_id: Optional[int] = None):
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

@router.post("/profile/messages/send")
async def send_profile_message(request: Request, chat_id: int = Form(...), message_content: str = Form(...)):
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
            
            if duplicate:
                cur.close()
                return RedirectResponse(url=f"/profile/messages?chat_id={chat_id}", status_code=303)

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

@router.post("/chat/initiate/{property_id}")
async def initiate_chat(property_id: int, request: Request):
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