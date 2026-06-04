from fastapi import APIRouter, Request, Query, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates  # 🚀 İŞTE EKSİK OLAN VE PROJEYİ ÇÖKÜRTEN SATIR BUYDU!
import database as db
import math
from typing import List
from psycopg2.extras import RealDictCursor

# listings.py ile tam uyumlu router ve template tanımı
router = APIRouter()
templates = Jinja2Templates(directory="templates")

# listings.py dosyasındaki format filtrelerini ve fonksiyonlarını aynen miras alıyoruz/bağlıyoruz
from routers.listings import process_property_data, format_currency

# --- API ENDPOINTS (JAVASCRIPT BAĞLANTILARI İÇİN) ---

@router.get("/api/favorites/my-list", response_model=List[int])
async def get_my_favorite_ids(request: Request):
    """Giriş yapmış kullanıcının favoriye eklediği ilanların sadece ID'lerini dizi olarak döner."""
    user_obj = db.get_user_from_request(request)
    if not user_obj:
        return [] # Giriş yapılmadıysa boş liste dön

    current_user_id = user_obj.get("id")
    conn = db.get_db_connection()
    if not conn:
        return []
        
    try:
        cur = conn.cursor()
        cur.execute("SELECT property_id FROM user_favorites WHERE user_id = %s", (current_user_id,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        # İki boyutlu array'i tek boyuta indirgeyip int olarak dönüyoruz
        return [int(row[0]) for row in rows]
    except Exception as e:
        print(f"Favori ID listesi çekilirken hata: {e}")
        if conn: conn.close()
        return []


@router.post("/api/favorites/add/{property_id}")
async def add_to_favorites(property_id: int, request: Request):
    """İlanı kullanıcının Neon DB'deki favori tablosuna kaydeder (Many-to-Many)."""
    user_obj = db.get_user_from_request(request)
    if not user_obj:
        return JSONResponse(status_code=401, content={"success": False, "message": "Lütfen önce giriş yapın."})

    current_user_id = user_obj.get("id")
    conn = db.get_db_connection()
    if not conn:
        return JSONResponse(status_code=500, content={"success": False, "message": "Veritabanı bağlantı hatası."})
        
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO user_favorites (user_id, property_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (current_user_id, property_id)
        )
        conn.commit()
        cur.close()
        conn.close()
        
        print(f"[FAVORITE ADD] Kullanıcı {current_user_id}, İlan {property_id} değerini CANLI DB'YE KAYDETTİ.")
        return {"success": True, "message": "İlan favorilerinize eklendi."}
    except Exception as e:
        if conn: conn.rollback(); conn.close()
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})


@router.post("/api/favorites/remove/{property_id}")
async def remove_from_favorites(property_id: int, request: Request):
    """İlanı kullanıcının favori tablosundan siler."""
    user_obj = db.get_user_from_request(request)
    if not user_obj:
        return JSONResponse(status_code=401, content={"success": False, "message": "Lütfen önce giriş yapın."})

    current_user_id = user_obj.get("id")
    conn = db.get_db_connection()
    if not conn:
        return JSONResponse(status_code=500, content={"success": False, "message": "Veritabanı bağlantı hatası."})
        
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM user_favorites WHERE user_id = %s AND property_id = %s",
            (current_user_id, property_id)
        )
        conn.commit()
        cur.close()
        conn.close()
        
        print(f"[FAVORITE REMOVE] Kullanıcı {current_user_id}, İlan {property_id} değerini CANLI DB'DEN SİLDİ.")
        return {"success": True, "message": "İlan favorilerinizden kaldırıldı."}
    except Exception as e:
        if conn: conn.rollback(); conn.close()
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})


# --- SAYFA ROUTER'I (PROFiLDEKi FAVORiLER SEKME GÖRÜNÜMÜ) ---

@router.get("/profile/favorites", response_class=HTMLResponse)
async def my_favorites_page(request: Request):
    user_obj = db.get_user_from_request(request)
    if not user_obj:
        return RedirectResponse(url="/home")

    current_user_id = user_obj.get("id")
    conn = db.get_db_connection()
    favorite_properties = []

    if conn:
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # p.* ile properties tablosundaki tüm ilan meta datalarını çekiyoruz
            query = """
                SELECT p.* FROM properties p
                JOIN user_favorites f ON p.id = f.property_id
                WHERE f.user_id = %s AND LOWER(TRIM(p.status)) NOT IN ('inactive', 'passive')
            """
            cur.execute(query, (current_user_id,))
            rows = cur.fetchall()
            
            for row in rows:
                item_dict = dict(row)
                # 🚀 BUG DÜZELTİLDİ: Olmayan item_copy yerine item_dict gönderildi!
                processed = process_property_data(item_dict) 
                favorite_properties.append(processed)
                
            cur.close()
            conn.close()
        except Exception as e:
            # Buradaki hata detayını terminalden okuyabilmek için print ekledik
            print(f"❌ CRITICAL FAVORITE DB ERROR: {e}")
            if conn: conn.close()

    u_image = "default_user.png"
    u_first = ""
    u_last = ""
    u_role = db.current_user_role or "user"

    if user_obj and isinstance(user_obj, dict):
        raw_img = user_obj.get("profile_image") or "default_user.png"
        u_image = str(raw_img).split('/')[-1] if "/" in str(raw_img) else str(raw_img)
        u_first = user_obj.get("first_name") or ""
        u_last = user_obj.get("last_name") or ""

    return templates.TemplateResponse(request, "favourites.html", {
        "request": request,
        "properties": favorite_properties,
        "favorite_properties": favorite_properties,
        "role": u_role,
        "profile_image": u_image, 
        "first_name": u_first,    
        "last_name": u_last,      
        "p_page": "favorites",   
        "user": user_obj
    })