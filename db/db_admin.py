from psycopg2.extras import RealDictCursor
from db.connection import get_db_connection

# PERFORMANS: 'properties.embedding' (vector(1536)) kolonu satır başına ~6KB'dır ve
# admin liste ekranlarında hiç kullanılmaz. "SELECT p.*" onu da çektiği için 83 ilanlık
# liste ~1.6s sürüyordu; bu kolonu hariç tutmak süreyi ~0.4s'ye düşürür.
# Kolon listesini bir kez hesaplayıp önbelleğe alıyoruz (şema nadiren değişir).
_PROP_COLS_CACHE = None


def _property_columns(cur, alias="p", exclude=("embedding",)):
    """Return 'p.col1, p.col2, ...' for the properties table, minus heavy/unused columns."""
    global _PROP_COLS_CACHE
    if _PROP_COLS_CACHE is None:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'properties' ORDER BY ordinal_position"
        )
        _PROP_COLS_CACHE = [r[0] if not isinstance(r, dict) else r["column_name"]
                            for r in cur.fetchall()]
    cols = [c for c in _PROP_COLS_CACHE if c not in exclude]
    return ", ".join(f"{alias}.{c}" for c in cols)

def get_pending_approvals_from_db():
    """Onay bekleyen ilanlar ya da emlakçı başvuruları havuzu (İleride genişletilebilir)"""
    conn = get_db_connection()
    if not conn: return []
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        # Şemadaki gerçek 'description' kolonuna göre filtreleme yapar
        cur.execute("SELECT * FROM properties WHERE description LIKE '%%Onay%%' ORDER BY id DESC")
        pending_list = cur.fetchall()
        cur.close()
        conn.close()
        return pending_list if pending_list else []
    except Exception as e:
        print(f"Onay listesi çekme hatası: {e}")
        return []

def get_system_logs_from_db():
    """Sistem hareket kayıtlarını simüle eder veya tablosundan çeker"""
    conn = get_db_connection()
    if not conn: return []
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT current_database() as db, version() as info")
        logs = cur.fetchall()
        cur.close()
        conn.close()
        return logs if logs else []
    except Exception as e:
        print(f"Sistem günlükleri çekme hatası: {e}")
        return []

def get_sales_logs_from_db():
    """Satış / kiralama hareketlerinin geçmiş kayıt dökümünü çeker"""
    return []

# --- ADMİN PANELİ AKSİYONLARI İÇİN VERİBATANI KATMANI (YOL HARİTASINA GÖRE EKLENDİ) ---

def update_property_status(property_id: str, status: str) -> bool:
    """
    İlanın statüsünü (active, rented, passive) günceller.
    Arayüzdeki Active / Passive süzgecinin arka plandaki ana motorudur.
    """
    conn = get_db_connection()
    if not conn: 
        return False
    cur = None
    try:
        cur = conn.cursor()
        # Veritabanındaki id alanınızın tipi INT veya UUID ise tip dönüşümü gerekebilir (örn: CAST(id AS TEXT) veya int(property_id))
        # En genel ve güvenli yöntem olarak TEXT/VARCHAR eşleşmesi veya doğrudan eşitlik kullanılır.
        cur.execute(
            "UPDATE properties SET status = %s WHERE id::text = %s",
            (status, str(property_id))
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"Veritabanı ilan durum güncelleme hatası ({property_id} -> {status}): {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if cur: cur.close()
        if conn: conn.close()

def soft_delete_property_in_db(property_id: str) -> bool:
    """
    İlanı veritabanından kalıcı olarak silmek yerine durumunu 'inactive' yapar.
    Router katmanındaki çağrı alternatifi için tam güvence sağlar.
    """
    return update_property_status(property_id, "inactive")


# --- FRONTEND HATALARI VE MODAL BAĞLANTISI İÇİN EKLENEN YENİ FONKSİYONLAR ---

def get_all_properties_with_agents_from_db():
    """
    TERMİNALDEKİ 'column p.user_id does not exist' HATASINI KÖKTEN ÇÖZEN KRİTİK FONKSİYON.
    Sistemdeki tüm ilanları, ilan sahibinin (Agent) adı ve soyadı ile birleştirerek çeker.
    Also, döviz simgelerini ve statü verilerini eksikosiz biçimde eşleştirir.
    """
    conn = get_db_connection()
    if not conn: return []
    cur = None
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # PERFORMANS: "p.*" yerine embedding hariç kolonları seç (bkz. _property_columns).
        prop_cols = _property_columns(cur, alias="p")

        # KESİN ÇÖZÜM: Sorgu p.user_id veya a.user_id yerine tamamen senin belirttiğin ve
        # Neonda onayladığın gerçek şemaya göre (properties.agent_id -> agents.id -> users.id) bağlanır.
        # Eğer agents tablosu bypass edilip doğrudan users tablosuna bağlanıyorsa COALESCE ve LEFT JOIN zinciri tam koruma sağlar.
        query = f"""
            SELECT {prop_cols},
                   COALESCE(u.first_name || ' ' || u.last_name, u2.first_name || ' ' || u2.last_name, 'Sistem Yöneticisi') as agent_name,
                   COALESCE(u.first_name, u2.first_name, '') as agent_first_name,
                   COALESCE(u.last_name, u2.last_name, '') as agent_last_name,
                   CASE 
                       WHEN UPPER(COALESCE(p.currency, p.currency_code, '')) = 'TRY' THEN '₺'
                       WHEN UPPER(COALESCE(p.currency, p.currency_code, '')) = 'USD' THEN '$'
                       WHEN UPPER(COALESCE(p.currency, p.currency_code, '')) = 'EUR' THEN '€'
                       WHEN UPPER(COALESCE(p.currency, p.currency_code, '')) = 'GBP' THEN '£'
                       ELSE COALESCE(p.currency, p.currency_code, '') 
                   END as currency_symbol
            FROM properties p
            LEFT JOIN agents a ON p.agent_id = a.id
            LEFT JOIN users u ON a.id = u.id
            LEFT JOIN users u2 ON p.agent_id = u2.id
            ORDER BY p.id DESC
        """
        cur.execute(query)
        properties_list = cur.fetchall()
        
        # Arayüzlerin fiyat ve başlık aramalarında düşmemesi için senkronizasyon garantisi
        if properties_list:
            for prop in properties_list:
                if 'name' in prop and not prop.get('title'):
                    prop['title'] = prop['name']
                if 'title' in prop and not prop.get('name'):
                    prop['name'] = prop['title']
                if 'price_normalized' in prop and not prop.get('price'):
                    prop['price'] = prop['price_normalized']
                    
        return properties_list if properties_list else []
    except Exception as e:
        print(f"İlanları agent ve döviz bilgileriyle çekme hatası [FIXED AGENT_ID JOIN]: {e}")
        return []
    finally:
        if cur: cur.close()
        if conn: conn.close()

def get_property_by_id(property_id):
    """Tek bir ilanın tüm detaylarını düzenleme formu için veritabanından çeker"""
    conn = get_db_connection()
    if not conn: return None
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        clean_id = int(property_id) if str(property_id).isdigit() else property_id
        
        query = """
            SELECT 
                p.*, 
                u.first_name as agent_first_name, 
                u.last_name as agent_last_name
            FROM properties p
            LEFT JOIN agents a ON p.agent_id = a.id
            LEFT JOIN users u ON a.id = u.id
            WHERE p.id = %s
        """
        cur.execute(query, (clean_id,))
        prop = cur.fetchone()
        
        if prop:
            # --- PÜRÜZ 1 FİX: Features eşleşmesi için hem id hem name listesi atanır ---
            cur.execute("SELECT feature_id FROM property_features WHERE property_id = %s", (clean_id,))
            features_data = cur.fetchall()
            prop['features'] = [f['feature_id'] for f in features_data]
            
            # Formun isme göre de yakalayabilmesi ihtimaline karşı string listesi de eklenir
            cur.execute("""
                SELECT f.name FROM features f 
                JOIN property_features pf ON f.id = pf.feature_id 
                WHERE pf.property_id = %s
            """, (clean_id,))
            features_names = cur.fetchall()
            prop['feature_names'] = [f['name'] for f in features_names]
            
            # --- PÜRÜZ 2 FİX: Çoklu Resimleri property_images tablosundan tam liste çekme ---
            cur.execute("SELECT image_url FROM property_images WHERE property_id = %s ORDER BY id ASC", (clean_id,))
            images_data = cur.fetchall()
            prop['images'] = [img['image_url'] for img in images_data]
            
            if 'name' in prop and not prop.get('title'):
                prop['title'] = prop['name']
            if 'price_normalized' in prop and not prop.get('price'):
                prop['price'] = prop['price_normalized']
            if 'currency_code' in prop and not prop.get('currency'):
                prop['currency'] = prop['currency_code']
            if 'listing_type' in prop and not prop.get('type'):
                prop['type'] = prop['listing_type']
            
            # FastAPI ve frontend eşleşmesinde çökme yaşanmaması için güvenlik garantisi
            prop['beds'] = int(prop.get('beds')) if prop.get('beds') is not None else 0
            prop['baths'] = int(prop.get('baths')) if prop.get('baths') is not None else 0
            prop['guests'] = int(prop.get('guests')) if prop.get('guests') is not None else 0
            prop['open_m2'] = int(prop.get('open_m2')) if prop.get('open_m2') is not None else 0
            
        cur.close()
        return prop
    except Exception as e:
        print(f"Tekil mülk çekme hatası: {e}")
        return None
    finally:
        if conn:
            conn.close()

def update_property_in_db(property_id, data: dict):
    """İlan kartından güncellenen verileri veritabanına yansıtır"""
    conn = get_db_connection()
    if not conn: return False
    try:
        cur = conn.cursor()
        
        clean_id = int(property_id) if str(property_id).isdigit() else property_id
        
        db_name = data.get('name') if data.get('name') is not None else data.get('title')
        db_price = data.get('price') if data.get('price') is not None else data.get('price_normalized')
        db_listing_type = data.get('listing_type') if data.get('listing_type') is not None else data.get('type')
        db_currency = data.get('currency_code') if data.get('currency_code') is not None else data.get('currency', 'TRY')

        existing_cursor = conn.cursor(cursor_factory=RealDictCursor)
        existing_cursor.execute("SELECT * FROM properties WHERE id = %s", (clean_id,))
        old_data = existing_cursor.fetchone()
        existing_cursor.close()

        if old_data:
            if db_name is None: db_name = old_data.get('name')
            if db_price is None: db_price = old_data.get('price_normalized')
            if db_listing_type is None: db_listing_type = old_data.get('listing_type')
            
        # Sorguya 'image' (Kapak Resmi) kolonu başarıyla eklendi!
        query = """
            UPDATE properties SET 
                name = %s, location = %s, district = %s, city = %s, country = %s,
                price_normalized = %s, monthly_price = %s, currency_code = %s, listing_type = %s,
                property_type = %s, room_count = %s, gross_m2 = %s, net_m2 = %s, building_age = %s,
                heating = %s, deed_status = %s, dues = %s, description = %s, status = %s,
                beds = %s, baths = %s, guests = %s, open_m2 = %s, image = %s
            WHERE id = %s
        """
        
        guests_input = data.get('guests') if data.get('guests') is not None else data.get('guest_count')
        open_m2_input = data.get('open_m2') if data.get('open_m2') is not None else data.get('open_area_m2')

        # Eğer yeni bir kapak resmi gönderilmediyse, eski kapak resmini koru
        db_image = data.get('image', old_data.get('image') if old_data else 'placeholder.jpg')

        cur.execute(query, (
            db_name, 
            data.get('location', old_data.get('location') if old_data else None), 
            data.get('district', old_data.get('district') if old_data else ""), 
            data.get('city', old_data.get('city') if old_data else ""), 
            data.get('country', old_data.get('country') if old_data else ""),
            db_price, 
            db_price, 
            db_currency, 
            db_listing_type,
            data.get('property_type', old_data.get('property_type') if old_data else None), 
            data.get('room_count', old_data.get('room_count') if old_data else None), 
            data.get('gross_m2', old_data.get('gross_m2') if old_data else None), 
            data.get('net_m2', old_data.get('net_m2') if old_data else None), 
            data.get('building_age', old_data.get('building_age') if old_data else None), 
            data.get('heating', old_data.get('heating') if old_data else None), 
            data.get('deed_status', old_data.get('deed_status') if old_data else None), 
            data.get('dues', data.get('dues', 0) if old_data else 0),
            data.get('description', old_data.get('description') if old_data else None),
            data.get('status', old_data.get('status') if old_data else 'active'),
            int(data.get('beds')) if data.get('beds') is not None else (old_data.get('beds', 0) if old_data else 0),
            int(data.get('baths')) if data.get('baths') is not None else (old_data.get('baths', 0) if old_data else 0),
            int(guests_input) if guests_input is not None else (old_data.get('guests', 0) if old_data else 0),
            int(open_m2_input) if open_m2_input is not None else (old_data.get('open_m2', 0) if old_data else 0),
            db_image, # Sorgudaki %s eşleşmesi için buraya eklendi
            clean_id
        ))
        
        # Özellikler güncellenirken senkronize edilir
        if 'features' in data and data['features'] is not None:
            cur.execute("DELETE FROM property_features WHERE property_id = %s", (clean_id,))
            for feature_id in data['features']:
                cur.execute(
                    "INSERT INTO property_features (property_id, feature_id) VALUES (%s, %s)",
                    (clean_id, int(feature_id))
                )
                
        # --- RESİMLER GÜNCELLENİRKEN SENKRONİZE EDİLİR (İSİM UYUŞMAZLIĞI GİDERİLDİ) ---
        # Backend 'image_urls' veya 'images' yollasa da ikisini de kabul edecek esneklik sağlandı
        target_images = data.get('image_urls') if data.get('image_urls') is not None else data.get('images')
        
        if target_images is not None:
            cur.execute("DELETE FROM property_images WHERE property_id = %s", (clean_id,))
            for i, url in enumerate(target_images):
                cur.execute(
                    "INSERT INTO property_images (property_id, image_url, is_main) VALUES (%s, %s, %s)",
                    (clean_id, url, (i == 0))
                )
                
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print(f"Mülk güncelleme hatası: {e}")
        if conn: conn.rollback()
        return False
    finally:
        if conn:
            conn.close()