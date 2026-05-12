import bcrypt
import psycopg2
import os
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# .env dosyasındaki verileri (DATABASE_URL vb.) sisteme yükler
load_dotenv()

# --- VERİTABANI BAĞLANTI AYARLARI ---
DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    """Neon PostgreSQL veritabanına canlı bağlantı açar"""
    if not DATABASE_URL:
        print("CRITICAL: DATABASE_URL .env dosyasında bulunamadı!")
        return None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        return conn
    except Exception as e:
        print(f"CRITICAL: Veritabanı bağlantı hatası: {e}")
        return None

# --- ŞİFRELEME FONKSİYONLARI ---
def hash_password(password: str):
    pwd_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode('utf-8')

def verify_password(plain_password, hashed_password):
    try:
        password_byte = plain_password.encode('utf-8')
        hashed_byte = hashed_password.encode('utf-8')
        return bcrypt.checkpw(password_byte, hashed_byte)
    except Exception:
        return False

# --- GLOBAL TAKİP DEĞİŞKENLERİ ---
current_user_email = None
current_user_role = "guest"
current_user_data = {}

# --- STATİK PROPERTIES (Hiçbir satırı silinmeden korunmuştur) ---

properties = {
    "1": {
        "id": "1", "name": "Villa Shiraz", "location": "Yeşilüzümlü, Fethiye", 
        "price": 35083, "currency_symbol": "₺", "currency_code": "TRY",
        "image": "villa.png", "type": "rent", "guests": 4, "beds": 6, "baths": 2, 
        "desc": "Fethiye'nin doğasında, modern mimari ve huzurun buluştuğu lüks kiralık villa.",
        "net_m2": 135, "gross_m2": 168, "open_m2": 30, "room_count": "3+1", "building_age": "10 ve üzeri", 
        "heating": "Kalorifer", "dues": 4500, "is_site": "Evet", "site_name": "57. Havacılar Sitesi",
        "is_credit": "Evet", "deed_status": "Kat İrtifaklı", "is_trade": "Evet"
    },
    "2": {
        "id": "2", "name": "Sea House", "location": "Kaş, Antalya", 
        "price": 1200, "currency_symbol": "$", "currency_code": "USD",
        "image": "villa2.png", "type": "rent", "guests": 2, "beds": 2, "baths": 1, 
        "desc": "Denize sıfır konumuyla Kaş'ın eşsiz turkuaz sularına açılan kiralık tatil evi.",
        "net_m2": 135, "gross_m2": 168, "open_m2": 30, "room_count": "1+1", "building_age": "5", 
        "heating": "Klima", "dues": 2000, "is_site": "Hayır", "site_name": "-",
        "is_credit": "Evet", "deed_status": "Müstakil Tapu", "is_trade": "Hayır"
    },
    "3": {
        "id": "3", "name": "Modern Villa", "location": "Bodrum, Muğla", 
        "price": 12490000, "currency_symbol": "₺", "currency_code": "TRY",
        "image": "villa3.png", "type": "sale", "guests": 8, "beds": 10, "baths": 5, 
        "desc": "Bodrum'un en prestijli bölgesinde, ultra lüks detaylarla donatılmış satılık modern malikane.",
        "net_m2": 450, "gross_m2": 550, "open_m2": 150, "room_count": "5+2", "building_age": "0 (Yeni)", 
        "heating": "Yerden Isıtma", "dues": 7500, "is_site": "Evet", "site_name": "Bodrum Elite Life",
        "is_credit": "Evet", "deed_status": "Kat Mülkiyeti", "is_trade": "Evet"
    },
    "4": {
        "id": "4", "name": "Olive Grove Manor", "location": "Bellapais, Girne, Kuzey Kıbrıs", 
        "price": 1500, "currency_symbol": "£", "currency_code": "GBP",
        "image": "villa4.png", "type": "rent", "guests": 8, "beds": 4, "baths": 3, 
        "desc": "Tarihi Bellapais Manastırı yakınında, zeytin ağaçları içinde huzur dolu, geleneksel taş mimari.",
        "net_m2": 220, "gross_m2": 280, "open_m2": 100, "room_count": "4+1", "building_age": "15", 
        "heating": "Şömine + Klima", "dues": 1500, "is_site": "Hayır", "site_name": "-",
        "is_credit": "Hayır", "deed_status": "Eşdeğer Koçan", "is_trade": "Hayır"
    },
    "5": {
        "id": "5", "name": "Sky Garden Loft", "location": "Girne, Merkez, Kuzey Kıbrıs", 
        "price": 250000, "currency_symbol": "€", "currency_code": "EUR",
        "image": "villa5.png", "type": "sale", "guests": 12, "beds": 9, "baths": 4, 
        "desc": "Şehrin kalbinde, akıllı ev sistemi ve panoramik şehir manzaralı özel teras bahçesi.",
        "net_m2": 320, "gross_m2": 380, "open_m2": 60, "room_count": "4+2", "building_age": "2", 
        "heating": "Merkezi", "dues": 3000, "is_site": "Evet", "site_name": "Sky Loft Residence",
        "is_credit": "Evet", "deed_status": "Türk Malı Koçan", "is_trade": "Evet"
    },
    "6": {
        "id": "6", "name": "Azure Infinity Villa", "location": "Esentepe, Sahil Yolu, Kuzey Kıbrıs", 
        "price": 45782, "currency_symbol": "₺", "currency_code": "TRY",
        "image": "villa6.png", "type": "rent", "guests": 10, "beds": 5, "baths": 5, 
        "desc": "Kesintisiz Akdeniz manzarasına açılan sonsuzluk havuzu ve özel plaj erişimi.",
        "net_m2": 280, "gross_m2": 350, "open_m2": 200, "room_count": "5+1", "building_age": "3", 
        "heating": "VRF Sistem", "dues": 5000, "is_site": "Evet", "site_name": "Azure Esentepe",
        "is_credit": "Evet", "deed_status": "Eşdeğer Koçan", "is_trade": "Hayır"
    },
    "7": {
        "id": "7", "name": "Pine Valley Estate", "location": "Alsancak, Girne, Kuzey Kıbrıs", 
        "price": 55000, "currency_symbol": "₺", "currency_code": "TRY",
        "image": "villa7.png", "type": "rent", "guests": 6, "beds": 4, "baths": 2, 
        "desc": "Çam ormanlarının içinde, temiz havası ve dağ manzarasıyla doğa tutkunları için müstakil ev.",
        "net_m2": 180, "gross_m2": 240, "open_m2": 500, "room_count": "3+1", "building_age": "8", 
        "heating": "Klima", "dues": 500, "is_site": "Hayır", "site_name": "-",
        "is_credit": "Evet", "deed_status": "Eşdeğer Koçan", "is_trade": "Evet"
    },
    "8": {
        "id": "8", "name": "Golden Sands Penthouse", "location": "İskele, Long Beach, Kuzey Kıbrıs", 
        "price": 350000, "currency_symbol": "£", "currency_code": "GBP",
        "image": "villa9.png", "type": "sale", "guests": 10, "beds": 5, "baths": 3, 
        "desc": "Ünlü Long Beach sahilinde, rezidans konforu ve 360 derece deniz manzaralı dev teras.",
        "net_m2": 210, "gross_m2": 260, "open_m2": 90, "room_count": "3+2", "building_age": "1", 
        "heating": "Yerden Isıtma", "dues": 3500, "is_site": "Evet", "site_name": "Long Beach Royal",
        "is_credit": "Evet", "deed_status": "Kat İrtifaklı", "is_trade": "Evet"
    },
    "9": {
        "id": "9", "name": "Citrus Garden Villa", "location": "Lefke, Kuzey Kıbrıs", 
        "price": 9850760, "currency_symbol": "₺", "currency_code": "TRY",
        "image": "villa8.png", "type": "sale", "guests": 8, "beds": 6, "baths": 3, 
        "desc": "Narenciye bahçeleri içerisinde, sakinlik arayanlar için ideal, modern rustik satılık villa.",
        "net_m2": 170, "gross_m2": 220, "open_m2": 1000, "room_count": "4+1", "building_age": "12", 
        "heating": "Klima", "dues": 200, "is_site": "Hayır", "site_name": "-",
        "is_credit": "Hayır", "deed_status": "Müstakil Koçan", "is_trade": "Evet"
    } 
}


# --- CANLI VERİTABANI: KULLANICI İŞLEMLERİ ---

def get_user_from_db(email):
    """E-posta adresiyle kullanıcıyı veritabanından bulur"""
    conn = get_db_connection()
    if not conn: return None
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cur.fetchone()
        cur.close()
        conn.close()
        return user
    except Exception as e:
        print(f"Kullanıcı çekme hatası: {e}")
        return None

def register_user_to_db(email, password, first_name, last_name, role="user"):
    """Yeni kullanıcıyı Neon DB'ye kaydeder"""
    conn = get_db_connection()
    if not conn: return False
    try:
        cur = conn.cursor()
        hashed = hash_password(password)
        query = """
            INSERT INTO users (email, password, first_name, last_name, role, profile_image) 
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        # Kayıt anında varsayılan profil resmi atanıyor
        cur.execute(query, (email, hashed, first_name, last_name, role, 'default_user.png'))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Kayıt hatası: {e}")
        return False

def update_user_in_db(email, data: dict):
    """Kullanıcı profilini (fotoğraf dahil) günceller"""
    conn = get_db_connection()
    if not conn: return
    try:
        cur = conn.cursor()
        # Dinamik şifre güncelleme desteği için kontrol eklenmiştir
        if data.get('password'):
            query = """
                UPDATE users 
                SET first_name = %s, last_name = %s, phone = %s, gender = %s, profile_image = %s, password = %s
                WHERE email = %s
            """
            cur.execute(query, (
                data['first_name'], 
                data['last_name'], 
                data.get('phone'), 
                data.get('gender'), 
                data.get('profile_image', 'default_user.png'),
                hash_password(data['password']),
                email
            ))
        else:
            query = """
                UPDATE users 
                SET first_name = %s, last_name = %s, phone = %s, gender = %s, profile_image = %s
                WHERE email = %s
            """
            cur.execute(query, (
                data['first_name'], 
                data['last_name'], 
                data.get('phone'), 
                data.get('gender'), 
                data.get('profile_image', 'default_user.png'), 
                email
            ))
        
        # Agent modundaysa Agent tablosundaki resmi de senkronize et
        if current_user_role == 'agent':
            cur.execute("UPDATE agents SET agent_image = %s WHERE id = (SELECT id FROM users WHERE email = %s)", (data.get('profile_image'), email))
            
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Güncelleme hatası: {e}")

# --- CANLI VERİTABANI: MÜLK VE ÖZELLİK İŞLEMLERİ ---

def get_properties_from_db():
    """Tüm ilanları Neon DB'den çeker."""
    conn = get_db_connection()
    if not conn: return []
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM properties ORDER BY id DESC")
        db_props = cur.fetchall()
        cur.close()
        conn.close()
        return db_props if db_props else []
    except Exception as e:
        print(f"Mülk çekme hatası: {e}")
        return []

def get_property_images(property_id):
    """Bir mülke ait tüm fotoğrafları getirir"""
    conn = get_db_connection()
    if not conn: return []
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT image_url FROM property_images WHERE property_id = %s", (property_id,))
        images = cur.fetchall()
        cur.close()
        conn.close()
        return [img['image_url'] for img in images]
    except Exception as e:
        print(f"Fotoğraf çekme hatası: {e}")
        return []

def get_property_features(property_id):
    """Bir mülke ait özellikleri getirir (Havuz, Otopark vb.)"""
    conn = get_db_connection()
    if not conn: return []
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        query = """
            SELECT f.name FROM features f
            JOIN property_features pf ON f.id = pf.feature_id
            WHERE pf.property_id = %s
        """
        cur.execute(query, (property_id,))
        features = cur.fetchall()
        cur.close()
        conn.close()
        return [f['name'] for f in features]
    except Exception as e:
        print(f"Özellik çekme hatası: {e}")
        return []

# --- AGENT (EMLAKÇI) İŞLEMLERİ ---

def get_property_agent_info(property_id):
    """İlan detay sayfasında o ilanın sahibini (Agent) getiren fonksiyon"""
    conn = get_db_connection()
    if not conn: return None
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        query = """
            SELECT u.id, (u.first_name || ' ' || u.last_name) as full_name, u.email, 
                   a.agency_name, a.phone_number, a.agent_image, a.is_verified, a.joined_at,
                   u.profile_image
            FROM properties p
            JOIN agents a ON p.agent_id = a.id
            JOIN users u ON a.id = u.id
            WHERE p.id = %s
        """
        cur.execute(query, (property_id,))
        agent_data = cur.fetchone()
        cur.close()
        conn.close()
        return agent_data
    except Exception as e:
        print(f"Agent bilgisi çekme hatası: {e}")
        return None

def get_agent_with_properties(agent_id):
    """Belirli bir emlakçının profilini ve tüm ilanlarını getirir"""
    conn = get_db_connection()
    if not conn: return None, []
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # 1. Agent ve User bilgilerini birleştir
        agent_query = """
            SELECT u.id, (u.first_name || ' ' || u.last_name) as full_name, u.email, 
                   a.agency_name, a.phone_number, a.agent_image, a.is_verified, a.bio, a.joined_at,
                   u.profile_image
            FROM users u
            JOIN agents a ON u.id = a.id
            WHERE u.id = %s
        """
        cur.execute(agent_query, (agent_id,))
        agent_info = cur.fetchone()
        
        if not agent_info:
            cur.close()
            conn.close()
            return None, []
            
        # 2. Agent'ın sahip olduğu tüm ilanları çek
        props_query = "SELECT * FROM properties WHERE agent_id = %s ORDER BY id DESC"
        cur.execute(props_query, (agent_id,))
        properties_list = cur.fetchall()
        
        cur.close()
        conn.close()
        return agent_info, properties_list
    except Exception as e:
        print(f"Agent portföyü çekme hatası: {e}")
        return None, []

# --- UYGULAMA MANTIĞI: LOGIN VE OTURUM ---

def login_user(email, password):
    """Kullanıcıyı DB'den kontrol eder ve global oturumu başlatır"""
    global current_user_email, current_user_role, current_user_data
    
    user = get_user_from_db(email)
    if user and verify_password(password, user['password']):
        current_user_email = user['email']
        current_user_role = user['role']
        current_user_data = dict(user)
        return True
    return False

def logout_user():
    """Oturumu sonlandırır"""
    global current_user_email, current_user_role, current_user_data
    current_user_email = None
    current_user_role = "guest"
    current_user_data = {}