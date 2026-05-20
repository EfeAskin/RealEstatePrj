from psycopg2.extras import RealDictCursor
from db.connection import get_db_connection

# --- STATİK PROPERTIES (Hata vermemesi için boş referans olarak korunmuştur) ---
properties = {}

# --- CANLI VERİTABANI: MÜLK VE ÖZELLİK İŞLEMLERİ ---

def get_all_properties_with_agents_from_db():
    """
    TERMİNALDEKİ 'column p.user_id does not exist' HATASINI KÖKTEN ÇÖZEN KRİTİK FONKSİYON.
    Admin panelindeki 'All Properties' sekmesinde pasif mülkler dahil tüm listeyi 
    doğru şema bağıntısıyla (properties.agent_id -> agents.id -> users.id) or doğrudan users tablosuna çeker.
    """
    conn = get_db_connection()
    if not conn: return []
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Sorgu tamamen senin belirttiğin hatasız şemaya göre fallback LEFT JOIN zinciri ile güncellendi
        query = """
            SELECT 
                p.*, 
                COALESCE(u.first_name, u2.first_name, '') as agent_first_name, 
                COALESCE(u.last_name, u2.last_name, '') as agent_last_name
            FROM properties p
            LEFT JOIN agents a ON p.agent_id = a.id
            LEFT JOIN users u ON a.id = u.id
            LEFT JOIN users u2 ON p.agent_id = u2.id
            ORDER BY p.id DESC;
        """
        cur.execute(query)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        
        # Arayüzün kırılmaması için isim ve fiyat maplemeleri garantilenir
        if rows:
            for prop in rows:
                if 'title_name' in prop:
                    prop['title'] = prop['title_name']
                    prop['name'] = prop['title_name']
                if 'name' in prop and not prop.get('title'):
                    prop['title'] = prop['name']
                if 'title' in prop and not prop.get('name'):
                    prop['name'] = prop['title']
                if 'price_normalized' in prop and not prop.get('price'):
                    prop['price'] = prop['price_normalized']
                if 'price' in prop and not prop.get('price_normalized'):
                    prop['price_normalized'] = prop['price']
                if 'currency' in prop and not prop.get('currency_code'):
                    prop['currency_code'] = prop['currency']
                if 'type' in prop and not prop.get('listing_type'):
                    prop['listing_type'] = prop['type']
                
                # 500 Hatası Önleyici Güvenlik Kolonları
                prop['beds'] = int(prop.get('beds')) if prop.get('beds') is not None else 0
                prop['baths'] = int(prop.get('baths')) if prop.get('baths') is not None else 0
                prop['guests'] = int(prop.get('guests')) if prop.get('guests') is not None else 0
                prop['open_m2'] = int(prop.get('open_m2')) if prop.get('open_m2') is not None else 0
                    
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"get_all_properties_with_agents_from_db hatası [FIXED AGENT_ID JOIN]: {e}")
        return []

def get_properties_from_db(include_passive: bool = False):
    """
    Veritabanındaki mülkleri çeker. Admin panelinin 'All' and 'Passive' sekmelerinde 
    pasif ilanları da görebilmesi için 'include_passive' parametresi eklenmiştir.
    """
    conn = get_db_connection()
    if not conn: return []
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        if include_passive:
            query = """
                SELECT 
                    p.*, 
                    COALESCE(u.first_name, u2.first_name, '') as agent_first_name, 
                    COALESCE(u.last_name, u2.last_name, '') as agent_last_name
                FROM properties p
                LEFT JOIN agents a ON p.agent_id = a.id
                LEFT JOIN users u ON a.id = u.id
                LEFT JOIN users u2 ON p.agent_id = u2.id
                ORDER BY p.id DESC
            """
            cur.execute(query)
        else:
            query = """
                SELECT 
                    p.*, 
                    COALESCE(u.first_name, u2.first_name, '') as agent_first_name, 
                    COALESCE(u.last_name, u2.last_name, '') as agent_last_name
                FROM properties p
                LEFT JOIN agents a ON p.agent_id = a.id
                LEFT JOIN users u ON a.id = u.id
                LEFT JOIN users u2 ON p.agent_id = u2.id
                WHERE (p.status != 'passive' AND p.status != 'approving') OR p.status IS NULL 
                ORDER BY p.id DESC
            """
            cur.execute(query)
            
        db_props = cur.fetchall()
        cur.close()
        conn.close()
        
        if db_props:
            for prop in db_props:
                if 'title_name' in prop:
                    prop['title'] = prop['title_name']
                    prop['name'] = prop['title_name']
                if 'name' in prop and not prop.get('title'):
                    prop['title'] = prop['name']
                if 'title' in prop and not prop.get('name'):
                    prop['name'] = prop['title']
                if 'price_normalized' in prop and not prop.get('price'):
                    prop['price'] = prop['price_normalized']
                if 'price' in prop and not prop.get('price_normalized'):
                    prop['price_normalized'] = prop['price']
                if 'currency' in prop and not prop.get('currency_code'):
                    prop['currency_code'] = prop['currency']
                if 'type' in prop and not prop.get('listing_type'):
                    prop['listing_type'] = prop['type']
                
                # 500 Hatası Önleyici Güvenlik Kolonları
                prop['beds'] = int(prop.get('beds')) if prop.get('beds') is not None else 0
                prop['baths'] = int(prop.get('baths')) if prop.get('baths') is not None else 0
                prop['guests'] = int(prop.get('guests')) if prop.get('guests') is not None else 0
                prop['open_m2'] = int(prop.get('open_m2')) if prop.get('open_m2') is not None else 0
                    
        return db_props if db_props else []
    except Exception as e:
        print(f"Mülk çekme hatası: {e}")
        return []

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
                COALESCE(u.first_name, u2.first_name, '') as agent_first_name, 
                COALESCE(u.last_name, u2.last_name, '') as agent_last_name
            FROM properties p
            LEFT JOIN agents a ON p.agent_id = a.id
            LEFT JOIN users u ON a.id = u.id
            LEFT JOIN users u2 ON p.agent_id = u2.id
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
            
            if 'title_name' in prop:
                prop['title'] = prop['title_name']
                prop['name'] = prop['title_name']
            if 'name' in prop and not prop.get('title'):
                prop['title'] = prop['name']
            if 'title' in prop and not prop.get('name'):
                prop['name'] = prop['title']
            if 'price_normalized' in prop and not prop.get('price'):
                prop['price'] = prop['price_normalized']
            if 'price' in prop and not prop.get('price_normalized'):
                prop['price_normalized'] = prop['price']
            if 'currency_code' in prop and not prop.get('currency'):
                prop['currency'] = prop['currency_code']
            if 'currency' in prop and not prop.get('currency_code'):
                prop['currency_code'] = prop['currency']
            if 'listing_type' in prop and not prop.get('type'):
                prop['type'] = prop['listing_type']
            if 'type' in prop and not prop.get('listing_type'):
                prop['listing_type'] = prop['type']
            
            # FastAPI ve frontend eşleşmesinde çökme yaşanmaması için güvenlik garantisi
            prop['beds'] = int(prop.get('beds')) if prop.get('beds') is not None else 0
            prop['baths'] = int(prop.get('baths')) if prop.get('baths') is not None else 0
            prop['guests'] = int(prop.get('guests')) if prop.get('guests') is not None else 0
            prop['open_m2'] = int(prop.get('open_m2')) if prop.get('open_m2') is not None else 0
            
        cur.close()
        conn.close()
        return prop
    except Exception as e:
        print(f"Tekil mülk çekme hatası: {e}")
        return None

def update_property_in_db(property_id, data: dict):
    """İlan kartından güncellenen verileri veritabanına yansıtır"""
    conn = get_db_connection()
    if not conn: return False
    try:
        cur = conn.cursor()
        
        clean_id = int(property_id) if str(property_id).isdigit() else property_id
        
        db_name = data.get('name') if data.get('name') is not None else data.get('title')
        if db_name is None:
            db_name = data.get('title_name')
            
        db_price = data.get('price') if data.get('price') is not None else data.get('price_normalized')
        db_listing_type = data.get('type') if data.get('type') is not None else data.get('listing_type')
        db_currency = data.get('currency') if data.get('currency') is not None else data.get('currency_code', 'TRY')

        existing_cursor = conn.cursor(cursor_factory=RealDictCursor)
        existing_cursor.execute("SELECT * FROM properties WHERE id = %s", (clean_id,))
        old_data = existing_cursor.fetchone()
        existing_cursor.close()

        if old_data:
            if db_name is None: db_name = old_data.get('title_name') or old_data.get('name') or old_data.get('title')
            if db_price is None: db_price = old_data.get('price') or old_data.get('price_normalized')
            if db_listing_type is None: db_listing_type = old_data.get('type') or old_data.get('listing_type')
            if db_currency is None: db_currency = old_data.get('currency') or old_data.get('currency_code')
            
        # Hem yeni title_name hem de eski name/title kolonları tam set şema senkronizasyonu için atanır
        query = """
            UPDATE properties SET 
                title_name = %s, name = %s, title = %s, location = %s, district = %s, city = %s, country = %s,
                price_normalized = %s, price = %s, monthly_price = %s, currency_code = %s, currency = %s, listing_type = %s, type = %s,
                property_type = %s, room_count = %s, gross_m2 = %s, net_m2 = %s, building_age = %s,
                heating = %s, deed_status = %s, dues = %s, description = %s, status = %s,
                beds = %s, baths = %s, guests = %s, open_m2 = %s
            WHERE id = %s
        """
        
        # HTML'den hem 'guest_count' hem de 'guests' olarak gelebilecek veriyi güvenli yakalama mantığı
        guests_input = data.get('guests') if data.get('guests') is not None else data.get('guest_count')
        open_m2_input = data.get('open_m2') if data.get('open_m2') is not None else data.get('open_area_m2')

        cur.execute(query, (
            db_name,
            db_name,
            db_name,
            data.get('location', old_data.get('location') if old_data else None), 
            data.get('district', old_data.get('district') if old_data else ""), 
            data.get('city', old_data.get('city') if old_data else ""), 
            data.get('country', old_data.get('country') if old_data else ""),
            db_price, 
            db_price,
            db_price, 
            db_currency,
            db_currency,
            db_listing_type,
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
                
        # Resimler güncellenirken senkronize edilir
        if 'images' in data and data['images'] is not None:
            cur.execute("DELETE FROM property_images WHERE property_id = %s", (clean_id,))
            for i, url in enumerate(data['images']):
                cur.execute(
                    "INSERT INTO property_images (property_id, image_url, is_main) VALUES (%s, %s, %s)",
                    (clean_id, url, (i == 0))
                )
                
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Mülk güncelleme hatası: {e}")
        if conn: conn.rollback()
        return False

def delete_property_from_db(property_id):
    """İlanı veritabanından tamamen silmez, durumunu 'passive' yapar (Soft Delete)"""
    conn = get_db_connection()
    if not conn: return False
    try:
        cur = conn.cursor()
        clean_id = int(property_id) if str(property_id).isdigit() else property_id
        cur.execute("UPDATE properties SET status = 'passive' WHERE id = %s", (clean_id,))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Mülk pasife alma hatası: {e}")
        if conn: conn.rollback()
        return False

def get_all_features_from_db():
    conn = get_db_connection()
    if not conn: return []
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, name FROM features ORDER BY name ASC")
        features = cur.fetchall()
        cur.close()
        conn.close()
        return features
    except Exception as e:
        print(f"Özellik listesi çekme hatası: {e}")
        return []

def get_property_images(property_id):
    conn = get_db_connection()
    if not conn: return []
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        clean_id = int(property_id) if str(property_id).isdigit() else property_id
        cur.execute("SELECT image_url FROM property_images WHERE property_id = %s", (clean_id,))
        images = cur.fetchall()
        cur.close()
        conn.close()
        return [img['image_url'] for img in images]
    except Exception as e:
        print(f"Fotoğraf çekme hatası: {e}")
        return []

def get_property_features(property_id):
    conn = get_db_connection()
    if not conn: return []
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        clean_id = int(property_id) if str(property_id).isdigit() else property_id
        query = """
            SELECT f.name FROM features f
            JOIN property_features pf ON f.id = pf.feature_id
            WHERE pf.property_id = %s
        """
        cur.execute(query, (clean_id,))
        features = cur.fetchall()
        cur.close()
        conn.close()
        return [f['name'] for f in features]
    except Exception as e:
        print(f"Özellik çekme hatası: {e}")
        return []

# --- AGENT (EMLAKÇI) İŞLEMLERİ ---

def add_full_property_to_db(agent_id, data: dict, selected_features: list, image_urls: list):
    """NEON DB KOLONLARIYLA TAM SENKRONİZE EDİLMİŞ GELİŞMİŞ EKLEME FONKSİYONU"""
    conn = get_db_connection()
    if not conn: return False
    try:
        cur = conn.cursor()
        
        # INSERT sorgusuna title_name, name/title, price_normalized/price, currency_code/currency ve listing_type/type alanları tam set eklendi
        prop_query = """
            INSERT INTO properties (
                title_name, name, title, location, district, city, country, 
                price_normalized, price, monthly_price, currency_code, currency, listing_type, type, 
                property_type, room_count, gross_m2, net_m2, building_age, 
                heating, deed_status, dues, description, image, agent_id, status,
                beds, baths, guests, open_m2
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """
        
        db_name = data.get('name') if data.get('name') is not None else data.get('title')
        if db_name is None:
            db_name = data.get('title_name')
            
        price_val = data.get('price') if data.get('price') is not None else data.get('price_normalized')
        db_listing_type = data.get('type') if data.get('type') is not None else data.get('listing_type', 'sale')
        db_currency = data.get('currency') if data.get('currency') is not None else data.get('currency_code', 'TRY')
        status_val = data.get('status', 'approving')
        clean_agent_id = int(agent_id) if str(agent_id).isdigit() else agent_id
        
        guests_input = data.get('guests') if data.get('guests') is not None else data.get('guest_count')
        open_m2_input = data.get('open_m2') if data.get('open_m2') is not None else data.get('open_area_m2')

        cur.execute(prop_query, (
            db_name, db_name, db_name, data['location'], data.get('district'), data.get('city'), data.get('country'),
            price_val, price_val, price_val, db_currency, db_currency, db_listing_type, db_listing_type, 
            data.get('property_type'), data.get('room_count'), data.get('gross_m2'), data.get('net_m2'), data.get('building_age'), 
            data.get('heating'), data.get('deed_status'), data.get('dues', 0), data.get('description'),
            image_urls[0] if image_urls else 'placeholder.jpg', clean_agent_id, status_val,
            int(data.get('beds')) if data.get('beds') is not None else 0,
            int(data.get('baths')) if data.get('baths') is not None else 0,
            int(guests_input) if guests_input is not None else 0,
            int(open_m2_input) if open_m2_input is not None else 0
        ))
        
        property_id = cur.fetchone()[0]

        if selected_features:
            for feature_id in selected_features:
                cur.execute(
                    "INSERT INTO property_features (property_id, feature_id) VALUES (%s, %s)",
                    (property_id, int(feature_id))
                )

        if image_urls:
            for i, url in enumerate(image_urls):
                cur.execute(
                    "INSERT INTO property_images (property_id, image_url, is_main) VALUES (%s, %s, %s)",
                    (property_id, url, (i == 0))
                )

        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        if conn: conn.rollback()
        print(f"Gelişmiş ilan ekleme hatası: {e}")
        return False

def add_new_property_to_db(agent_id, data: dict):
    """BASİT FORM İÇİN GÜNCEL SORGUNUN NEON DB İLE UYUMU"""
    conn = get_db_connection()
    if not conn: return False
    try:
        cur = conn.cursor()
        
        query = """
            INSERT INTO properties (
                title_name, name, title, location, district, city, country, 
                price_normalized, price, monthly_price, listing_type, type, room_count, net_m2, 
                description, image, agent_id, status, beds, baths, guests, open_m2
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        db_name = data.get('name') if data.get('name') is not None else data.get('title')
        if db_name is None:
            db_name = data.get('title_name')
            
        db_price = data.get('price') if data.get('price') is not None else data.get('price_normalized')
        db_type = data.get('type') if data.get('type') is not None else data.get('listing_type', 'sale')
        status_val = data.get('status', 'approving')
        clean_agent_id = int(agent_id) if str(agent_id).isdigit() else agent_id
        
        guests_input = data.get('guests') if data.get('guests') is not None else data.get('guest_count')
        open_m2_input = data.get('open_m2') if data.get('open_m2') is not None else data.get('open_area_m2')
        
        cur.execute(query, (
            db_name, db_name, db_name, data['location'], data.get('district'), data.get('city'), data.get('country'),
            db_price, db_price, db_price, db_type, db_type, data.get('room_count', '0'), data.get('net_m2', 0),
            data.get('description', ''), data.get('image', 'placeholder.jpg'),
            clean_agent_id, status_val,
            int(data.get('beds')) if data.get('beds') is not None else 0,
            int(data.get('baths')) if data.get('baths') is not None else 0,
            int(guests_input) if guests_input is not None else 0,
            int(open_m2_input) if open_m2_input is not None else 0
        ))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Basit ilan ekleme hatası: {e}")
        return False

def get_property_agent_info(property_id):
    conn = get_db_connection()
    if not conn: return None
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        clean_id = int(property_id) if str(property_id).isdigit() else property_id
        query = """
            SELECT u.id, (u.first_name || ' ' || u.last_name) as full_name, u.email, 
                   a.agency_name, a.phone_number, a.agent_image, a.is_verified, a.joined_at,
                   u.profile_image
            FROM properties p
            LEFT JOIN agents a ON p.agent_id = a.id
            LEFT JOIN users u ON a.id = u.id
            LEFT JOIN users u2 ON p.agent_id = u2.id
            WHERE p.id = %s
        """
        cur.execute(query, (clean_id,))
        agent_data = cur.fetchone()
        
        # Eğer doğrudan users tablosuna bağlıysa ve agent verisi boşsa koruma mappingleri
        if agent_data and not agent_data.get('id'):
            cur.execute("SELECT id, (first_name || ' ' || last_name) as full_name, email, profile_image FROM users WHERE id = (SELECT agent_id FROM properties WHERE id = %s)", (clean_id,))
            direct_user = cur.fetchone()
            if direct_user:
                agent_data.update(direct_user)
                
        cur.close()
        conn.close()
        return agent_data
    except Exception as e:
        print(f"Agent bilgisi çekme hatası: {e}")
        return None

def get_agent_with_properties(agent_id):
    conn = get_db_connection()
    if not conn: return None, []
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        clean_agent_id = int(agent_id) if str(agent_id).isdigit() else agent_id
        agent_query = """
            SELECT u.id, (u.first_name || ' ' || u.last_name) as full_name, u.email, 
                   COALESCE(a.agency_name, '') as agency_name, COALESCE(a.phone_number, '') as phone_number, 
                   COALESCE(a.agent_image, u.profile_image) as agent_image, COALESCE(a.is_verified, FALSE) as is_verified, 
                   COALESCE(a.bio, '') as bio, a.joined_at, u.profile_image
            FROM users u
            LEFT JOIN agents a ON u.id = a.id
            WHERE u.id = %s
        """
        cur.execute(agent_query, (clean_agent_id,))
        agent_info = cur.fetchone()
        if not agent_info:
            cur.close()
            conn.close()
            return None, []
            
        props_query = "SELECT * FROM properties WHERE agent_id = %s AND (status != 'passive' OR status IS NULL) ORDER BY id DESC"
        cur.execute(props_query, (clean_agent_id,))
        properties_list = cur.fetchall()
        
        if properties_list:
            for prop in properties_list:
                if 'title_name' in prop:
                    prop['title'] = prop['title_name']
                    prop['name'] = prop['title_name']
                if 'name' in prop and not prop.get('title'):
                    prop['title'] = prop['name']
                if 'title' in prop and not prop.get('name'):
                    prop['name'] = prop['title']
                if 'price_normalized' in prop and not prop.get('price'):
                    prop['price'] = prop['price_normalized']
                if 'price' in prop and not prop.get('price_normalized'):
                    prop['price_normalized'] = prop['price']
                if 'currency' in prop and not prop.get('currency_code'):
                    prop['currency_code'] = prop['currency']
                if 'type' in prop and not prop.get('listing_type'):
                    prop['listing_type'] = prop['type']
                    
                # 500 Hatası Önleyici Güvenlik Kolonları
                prop['beds'] = int(prop.get('beds')) if prop.get('beds') is not None else 0
                prop['baths'] = int(prop.get('baths')) if prop.get('baths') is not None else 0
                prop['guests'] = int(prop.get('guests')) if prop.get('guests') is not None else 0
                prop['open_m2'] = int(prop.get('open_m2')) if prop.get('open_m2') is not None else 0
                    
        cur.close()
        conn.close()
        return agent_info, properties_list
    except Exception as e:
        print(f"Agent portföyü çekme hatası: {e}")
        return None, []

# --- SİTENİN HER YERİNDE OKUNMAMIŞ BİLDİRİM SAYISINI TETİKLEYEN YENİ EK FONKSİYON ---

def get_unread_messages_count_from_db(user_id):
    """
    Kullanıcının okumadığı toplam mesaj sayısını döner.
    Giriş yapan kullanıcının ID'sine göre receiver_id eşleşmesi yapar.
    """
    conn = get_db_connection()
    if not conn: return 0
    try:
        cur = conn.cursor()
        query = "SELECT COUNT(*) FROM messages WHERE receiver_id = %s AND is_read = FALSE"
        cur.execute(query, (int(user_id),))
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        return count
    except Exception as e:
        print(f"get_unread_messages_count_from_db hatası: {e}")
        return 0