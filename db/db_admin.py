from psycopg2.extras import RealDictCursor
from db.connection import get_db_connection

def get_pending_approvals_from_db():
    """Onay bekleyen ilanlar ya da emlakçı başvuruları havuzu (İleride genişletilebilir)"""
    conn = get_db_connection()
    if not conn: return []
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
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
    İlanı veritabanından kalıcı olarak silmek yerine durumunu 'passive' yapar.
    Router katmanındaki çağrı alternatifi için tam güvence sağlar.
    """
    return update_property_status(property_id, "passive")


# --- FRONTEND HATALARI VE MODAL BAĞLANTISI İÇİN EKLENEN YENİ FONKSİYONLAR ---

def get_all_properties_with_agents_from_db():
    """
    TERMİNALDEKİ 'column p.user_id does not exist' HATASINI KÖKTEN ÇÖZEN KRİTİK FONKSİYON.
    Sistemdeki tüm ilanları, ilan sahibinin (Agent) adı ve soyadı ile birleştirerek çeker.
    Also, döviz simgelerini ve statü verilerini eksiksiz biçimde eşleştirir.
    """
    conn = get_db_connection()
    if not conn: return []
    cur = None
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # KESİN ÇÖZÜM: Sorgu p.user_id veya a.user_id yerine tamamen senin belirttiğin ve 
        # Neonda onayladığın gerçek şemaya göre (properties.agent_id -> agents.id -> users.id) bağlanır.
        # Hem orijinal kodundaki 'currency' alanını hem de 'currency_code' alternatifini COALESCE ile korur.
        query = """
            SELECT p.*, 
                   (u.first_name || ' ' || u.last_name) as agent_name,
                   u.first_name as agent_first_name,
                   u.last_name as agent_last_name,
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
            ORDER BY p.id DESC
        """
        cur.execute(query)
        properties_list = cur.fetchall()
        
        # Arayüzlerin fiyat ve başlık aramalarında düşmemesi için senkronizasyon garantisi
        if properties_list:
            for prop in properties_list:
                if 'name' in prop and not prop.get('title'):
                    prop['title'] = prop['name']
                if 'price_normalized' in prop and not prop.get('price'):
                    prop['price'] = prop['price_normalized']
                    
        return properties_list if properties_list else []
    except Exception as e:
        print(f"İlanları agent ve döviz bilgileriyle çekme hatası [FIXED AGENT_ID JOIN]: {e}")
        return []
    finally:
        if cur: cur.close()
        if conn: conn.close()

def get_property_by_id_from_db(property_id: str):
    """
    Düzenleme (Edit) modalı açıldığında, formun içini veritabanındaki 
    mevcut verilerle doldurmak için tekil ilan verisi getirir.
    """
    conn = get_db_connection()
    if not conn: return None
    cur = None
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM properties WHERE id::text = %s", (str(property_id),))
        property_data = cur.fetchone()
        
        # Modal içindeki alanların (title/price/currency) boş kalmaması için fallback eşlemeleri
        if property_data:
            if 'name' in property_data and not property_data.get('title'):
                property_data['title'] = property_data['name']
            if 'price_normalized' in property_data and not property_data.get('price'):
                property_data['price'] = property_data['price_normalized']
            if 'currency_code' in property_data and not property_data.get('currency'):
                property_data['currency'] = property_data['currency_code']
                
        return property_data
    except Exception as e:
        print(f"Tekil ilan çekme hatası (ID: {property_id}): {e}")
        return None
    finally:
        if cur: cur.close()
        if conn: conn.close()