import bcrypt
import psycopg2
import os
import time
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Yeni oluşturduğumuz db paketindeki tüm fonksiyonları ve değişkenleri içeri aktarıyoruz
from db.connection import (
    get_db_connection, execute_query, hash_password, verify_password,
    current_user_email, current_user_role, current_user_data
)
from db.auth_user import (
    get_user_from_db, register_user_to_db, update_user_in_db, get_all_users_from_db,
    login_user, logout_user
)
from db.properties import (
    properties, get_properties_from_db, get_property_by_id, update_property_in_db,
    delete_property_from_db, get_all_features_from_db, get_property_images,
    get_property_features, add_full_property_to_db, add_new_property_to_db,
    get_property_agent_info, get_agent_with_properties
)
from db.db_admin import (
    get_pending_approvals_from_db, get_system_logs_from_db, get_sales_logs_from_db,
    get_all_properties_with_agents_from_db as get_all_properties_fixed # db_admin'deki hatasız fonksiyonu import ediyoruz
)

# --- KÖPRÜ (PROXY) EKLEMELERİ VE ESNEK FONKSİYON EŞLEŞTİRMELERİ ---
# backend.py ve db/admin.py içerisindeki alternatif fonksiyon çağrılarının 
# doğrudan bu dosya üzerinden kırılmadan çalışabilmesi için takma isimler (alias) tanımlandı.

def get_property_by_id_from_db(property_id):
    """
    Neon DB veri tipi uyuşmazlığından kaynaklanan 500 hatasını önlemek 
    und modal formunu doldurabilmek amacıyla yazılmış güvenli tekil ilan çekme fonksiyonu.
    PÜRÜZ ÇÖZÜCÜ: İlişkili tablolardaki features ve çoklu resimleri de pakete dahil eder.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        # Gelen string ID değerini veritabanı tipi olan integer'a güvenle dönüştürüyoruz
        clean_id = int(property_id)
        query = "SELECT * FROM properties WHERE id = %s;"
        cursor.execute(query, (clean_id,))
        row = cursor.fetchone()
        
        if row:
            # RealDictCursor'dan gelen row yapısını JSONResponse için ham standart sözlüğe çeviriyoruz
            prop_dict = dict(row)
            
            # --- PÜRÜZ ÇÖZÜCÜ: guests ve open_m2 alanlarının geriye veri nesnesi olarak beslenmesi ---
            if 'guests' in prop_dict:
                prop_dict['guests'] = row['guests']
            if 'open_m2' in prop_dict:
                prop_dict['open_m2'] = row['open_m2']
            
            # --- PÜRÜZ ÇÖZÜCÜ EKLEME: Ek tablolardan verileri güvenle çekip sözlüğe ekliyoruz ---
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
            conn.close()
            return prop_dict
            
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"get_property_by_id_from_db hatası [ID TİP DÖNÜŞÜMÜ]: {e}")
    
    # Fallback koruması: Herhangi bir aksilikte orijinal üst katman fonksiyonunu tetikle
    try:
        return get_property_by_id(property_id)
    except:
        return None

# Tekil ilan çekme fonksiyon eşleştirmeleri
get_property_from_db = get_property_by_id_from_db

def get_all_properties_with_agents_from_db():
    """
    Neon DB şemasındaki 'user_id' hatasını kökten çözmek için doğrudan
    db_admin.py içerisinde yazdığımız, pasif ilanları da getiren güvenli JOIN motorunu çalıştırır.
    """
    try:
        # KESİN ÇÖZÜM: db_admin.py içinde yazdığın, properties.agent_id'ye bakan hatasız fonksiyonu döndürüyoruz.
        return get_all_properties_fixed()
    except Exception as e:
        print(f"get_all_properties_with_agents_from_db köprü hatası: {e}")
        # Fallback koruması: Orijinal fonksiyonu çağır
        return get_properties_from_db()

# İlan durumunu güncelleyen veya soft-delete (pasife alma) yapan fonksiyon eşleştirmeleri
# Eğer db.properties içinde spesifik bir durum güncelleme yoksa, genel update fonksiyonuna yönlendirilir.
def update_property_status(property_id: str, status: str) -> bool:
    """İlanın durumunu (active/passive/rented) günceller."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = "UPDATE properties SET status = %s WHERE id = %s;"
        cursor.execute(query, (status, int(property_id)))
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print(f"update_property_status hatası: {e}")
        try:
            return update_property_in_db(int(property_id), {"status": status})
        except:
            return update_property_in_db(property_id, {"status": status})

def soft_delete_property_in_db(property_id: str) -> bool:
    """İlanı silmek yerine durumunu passive çekerek soft-delete uygular."""
    return update_property_status(property_id, "passive")

# Not: Bu dosya, projenin eski 'import database' kullanan yerlerinin kırılmaması 
# için bir köprü (proxy) görevi görmektedir. Tüm lojik db/ klasörüne taşınmıştır.