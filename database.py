import os
import time
from datetime import datetime
from decimal import Decimal
import bcrypt
import psycopg2
import pytz  # Sunucu ile uygulama arasındaki 3 saatlik kaymayı düzeltmek için eklendi
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor

# Yeni oluşturulan db paketindeki tüm fonksiyonları ve değişkenleri içeri aktarıyoruz
from db.connection import (
    get_db_connection,
    execute_query,
    hash_password,
    verify_password,
)
from db.auth_user import (
    get_user_from_db,
    register_user_to_db,
    update_user_in_db,
    get_all_users_from_db,
    login_user,
    logout_user,
)
from db.properties import (
    properties,
    get_properties_from_db,
    get_property_by_id,
    update_property_in_db,
    delete_property_from_db,
    get_all_features_from_db,
    get_property_images,
    get_property_features,
    add_full_property_to_db,
    add_new_property_to_db,
    get_property_agent_info,
    get_agent_with_properties,
)
from db.db_admin import (
    get_pending_approvals_from_db,
    get_system_logs_from_db,
    get_sales_logs_from_db,
    get_all_properties_with_agents_from_db as get_all_properties_fixed,  # db_admin'deki hatasız fonksiyonu import ediyoruz
)

# --- BACKEND.PY İÇİN GEREKLİ KÜRESEL DEĞİŞKEN ALTYAPILARI (STATE MANAGEMENT) ---
current_user_email = None
current_user_role = "guest"
current_user_data = {}

# Türkiye Zaman Dilimi Tanımlaması
tr_tz = pytz.timezone("Europe/Istanbul")


# --- 3 SAAT KAYMA HATASINI ENGELLEYEN GÜVENLİ BAĞLANTI YÖNETİCİSİ ---
def get_synchronized_db_connection():
    """
    Veritabanı bağlantısını açar ve Neon PostgreSQL sunucusuna 
    oturum zaman diliminin 'Europe/Istanbul' (+3) olduğunu bildirir.
    Böylece veritabanı tarafında tetiklenen NOW() veya CURRENT_TIMESTAMP 
    fonksiyonları saat hatası üretmez.
    """
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            # PostgreSQL oturum saat dilimini kalıcı olarak Türkiye saatine set ediyoruz
            cur.execute("SET TIME ZONE 'Europe/Istanbul';")
            cur.close()
        except Exception as e:
            print(f"Veritabanı Zaman Dilimi Senkronizasyon Hatası: {e}")
    return conn


# --- 2. YOL İÇİN EKLENEN SİHİRLİ SESSIONS / COOKIE KORUMA FONKSİYONU ---
def get_user_from_cookie(user_id_str: str):
    """
    Tarayıcıdan gelen ham çerez (cookie) ID bilgisini alıp,
    veritabanından o kişiye ait güncel profil, şifre hash'i ve rol bilgisini döner.
    """
    if not user_id_str:
        return None
    
    conn = get_synchronized_db_connection()
    if not conn:
        return None
        
    try:
        # Gelen cookie string değerini güvenle integer'a çeviriyoruz
        clean_user_id = int(user_id_str) if str(user_id_str).isdigit() else None
        if clean_user_id is None:
            return None

        cur = conn.cursor(cursor_factory=RealDictCursor)
        # Sorguya 'password' alanı eklenerek auth işlemleri güvenceye alınmıştır.
        cur.execute(
            "SELECT id, role, first_name, last_name, email, password, company_name, profile_image FROM users WHERE id = %s",
            (clean_user_id,)
        )
        user = cur.fetchone()
        cur.close()
        return user
    except Exception as e:
        print(f"get_user_from_cookie hatası [COOKIE OKUMA]: {e}")
        return None
    finally:
        if conn:
            conn.close()


def get_user_by_email(email: str):
    """E-posta adresi ile kullanıcıyı şifresi dahil çekerek login akışını korur."""
    conn = get_synchronized_db_connection()
    if not conn:
        return None
        
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT id, role, first_name, last_name, email, password, company_name, profile_image FROM users WHERE email = %s",
            (email,)
        )
        user = cur.fetchone()
        cur.close()
        return user
    except Exception as e:
        print(f"get_user_by_email hatası: {e}")
        return None
    finally:
        if conn:
            conn.close()


# --- KÖPRÜ (PROXY) EKLEMELERİ VE ESNEK FONKSİYON EŞLEŞTİRMELERİ ---
def get_property_by_id_from_db(property_id):
    """
    Neon DB veri tipi uyuşmazlığından kaynaklanan 500 hatasını önlemek 
    ve modal formunu doldurabilmek amacıyla yazılmış güvenli tekil ilan çekme fonksiyonu.
    İlişkili tablolardaki features ve çoklu resimleri de pakete dahil eder.
    """
    conn = get_synchronized_db_connection()
    if not conn:
        return None
        
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        # Gelen string ID değerini veritabanı tipi olan integer'a güvenle dönüştürüyoruz
        clean_id = int(property_id) if str(property_id).isdigit() else property_id
        
        query = "SELECT * FROM properties WHERE id = %s;"
        cursor.execute(query, (clean_id,))
        row = cursor.fetchone()
        
        if row:
            # RealDictCursor'dan gelen row yapısını JSONResponse için ham standart sözlüğe çeviriyoruz
            prop_dict = dict(row)
            
            # --- ALIAS VE UYUMLULUK MOTORU (FRONTEND / BACKEND EŞLEME) ---
            if 'name' in prop_dict and not prop_dict.get('title'):
                prop_dict['title'] = prop_dict['name']
            if 'title' in prop_dict and not prop_dict.get('name'):
                prop_dict['name'] = prop_dict['title']
            
            if 'price_normalized' in prop_dict and not prop_dict.get('price'):
                prop_dict['price'] = prop_dict['price_normalized']
            if 'price' in prop_dict and not prop_dict.get('price_normalized'):
                prop_dict['price_normalized'] = prop_dict['price']
                
            if 'currency' in prop_dict and not prop_dict.get('currency_code'):
                prop_dict['currency_code'] = prop_dict['currency']
            if 'currency_code' in prop_dict and not prop_dict.get('currency'):
                prop_dict['currency'] = prop_dict['currency_code']
                
            if 'type' in prop_dict and not prop_dict.get('listing_type'):
                prop_dict['listing_type'] = prop_dict['type']
            if 'listing_type' in prop_dict and not prop_dict.get('type'):
                prop_dict['type'] = prop_dict['listing_type']
            
            # --- GÜVENLİ TİP DÖNÜŞÜMLERİ VE ZAMAN DUYARLILIĞI ---
            prop_dict['beds'] = int(prop_dict.get('beds')) if prop_dict.get('beds') is not None else 0
            prop_dict['baths'] = int(prop_dict.get('baths')) if prop_dict.get('baths') is not None else 0
            prop_dict['guests'] = int(prop_dict.get('guests')) if prop_dict.get('guests') is not None else 0
            prop_dict['open_m2'] = int(prop_dict.get('open_m2')) if prop_dict.get('open_m2') is not None else 0
            
            # Eğer ilan verilerinde bir datetime varsa ve naive ise yerelleştiriyoruz
            for k, v in prop_dict.items():
                if isinstance(v, datetime) and v.tzinfo is None:
                    prop_dict[k] = tr_tz.localize(v)

            # --- İLİŞKİLİ TABLO VERİLERİNİN ENJEKSİYONU ---
            # 1. Özellik ID listesini ekle
            cursor.execute("SELECT feature_id FROM property_features WHERE property_id = %s", (clean_id,))
            features_data = cursor.fetchall()
            prop_dict['features'] = [f['feature_id'] for f in features_data]
            
            # 2. Özellik isim listesini ekle
            cursor.execute("""
                SELECT f.name FROM features f 
                JOIN property_features pf ON f.id = pf.feature_id 
                WHERE pf.property_id = %s
            """, (clean_id,))
            features_names = cursor.fetchall()
            prop_dict['feature_names'] = [f['name'] for f in features_names]
            
            # 3. Çoklu resimlerin link listesini ekle
            cursor.execute("SELECT image_url FROM property_images WHERE property_id = %s ORDER BY id ASC", (clean_id,))
            images_data = cursor.fetchall()
            prop_dict['images'] = [img['image_url'] for img in images_data]
            
            cursor.close()
            return prop_dict
            
        cursor.close()
        return None
    except Exception as e:
        print(f"get_property_by_id_from_db hatası [ID TİP DÖNÜŞÜMÜ]: {e}")
        # Fallback koruması: Herhangi bir aksilikte orijinal üst katman fonksiyonunu tetikle
        try:
            return get_property_by_id(property_id)
        except:
            return None
    finally:
        if conn:
            conn.close()


# Tekil ilan çekme fonksiyon alias eşleştirmesi
get_property_from_db = get_property_by_id_from_db


def get_all_properties_with_agents_from_db():
    """
    Neon DB şemasındaki 'user_id' uyuşmazlığını çözmek için doğrudan
    db_admin.py içerisinde tanımlanan, pasif ilanları da getiren güvenli JOIN motorunu çalıştırır.
    """
    try:
        return get_all_properties_fixed()
    except Exception as e:
        print(f"get_all_properties_with_agents_from_db köprü hatası: {e}")
        # Fallback koruması: Orijinal ana fonksiyonu çağır
        return get_properties_from_db()


def update_property_status(property_id: str, status: str) -> bool:
    """İlanın durumunu (active/passive/approving/rented) doğrudan günceller."""
    conn = get_synchronized_db_connection()
    if not conn:
        return False
        
    try:
        cursor = conn.cursor()
        clean_id = int(property_id) if str(property_id).isdigit() else property_id
        query = "UPDATE properties SET status = %s WHERE id = %s;"
        cursor.execute(query, (status, clean_id))
        conn.commit()
        cursor.close()
        return True
    except Exception as e:
        print(f"update_property_status hatası: {e}")
        if conn:
            conn.rollback()
        # Fallback koruması: Genel update fonksiyonuna yönlendir
        try:
            clean_id = int(property_id) if str(property_id).isdigit() else property_id
            return update_property_in_db(clean_id, {"status": status})
        except:
            return False
    finally:
        if conn:
            conn.close()


def soft_delete_property_in_db(property_id: str) -> bool:
    """İlanı sistemden tamamen silmek yerine durumunu 'passive' çekerek soft-delete uygular."""
    return update_property_status(property_id, "passive")