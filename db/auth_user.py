from psycopg2.extras import RealDictCursor
from db.connection import get_db_connection, hash_password, verify_password
import db.connection as conn_mod

# --- CANLI VERİTABANI: KULLANICI İŞLEMLERİ ---
def get_user_from_db(email):
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
    """Yeni kullanıcıyı kaydeder ve oluşan ID'yi geri döndürür"""
    conn = get_db_connection()
    if not conn: return None
    try:
        cur = conn.cursor()
        hashed = hash_password(password)
        query = """
            INSERT INTO users (email, password, first_name, last_name, role, profile_image) 
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
        """
        cur.execute(query, (email, hashed, first_name, last_name, role, 'default_user.png'))
        new_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return new_id
    except Exception as e:
        print(f"Kayıt hatası: {e}")
        if conn: conn.rollback()
        return None

def update_user_in_db(email, data: dict):
    conn = get_db_connection()
    if not conn: return
    try:
        cur = conn.cursor()
        if data.get('password'):
            query = """
                UPDATE users 
                SET first_name = %s, last_name = %s, phone = %s, gender = %s, profile_image = %s, password = %s
                WHERE email = %s
            """
            cur.execute(query, (
                data['first_name'], data['last_name'], data.get('phone'), data.get('gender'), 
                data.get('profile_image', 'default_user.png'), hash_password(data['password']), email
            ))
        else:
            query = """
                UPDATE users 
                SET first_name = %s, last_name = %s, phone = %s, gender = %s, profile_image = %s
                WHERE email = %s
            """
            cur.execute(query, (
                data['first_name'], data['last_name'], data.get('phone'), data.get('gender'), 
                data.get('profile_image', 'default_user.png'), email
            ))
        
        # Eğer kullanıcı bir agent ise agents tablosundaki image bilgisini de güncelle
        if conn_mod.current_user_role == 'agent':
            cur.execute("UPDATE agents SET agent_image = %s WHERE id = (SELECT id FROM users WHERE email = %s)", 
                        (data.get('profile_image'), email))
            
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Güncelleme hatası: {e}")

def login_user(email, password):
    user = get_user_from_db(email)
    if user and verify_password(password, user['password']):
        conn_mod.current_user_email = user['email']
        conn_mod.current_user_role = user['role']
        conn_mod.current_user_data = dict(user)
        return True
    return False

def logout_user():
    conn_mod.current_user_email = None
    conn_mod.current_user_role = "guest"
    conn_mod.current_user_data = {}

# --- CRITICAL ADMIN EXTENSIONS (Eksiksiz Yönetimsel Güncellemeler) ---
def get_all_users_from_db():
    """Yöneticinin tüm kullanıcıları görebilmesi için veritabanındaki tüm üyeleri çeker"""
    conn = get_db_connection()
    if not conn: return []
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, email, first_name, last_name, role, phone, gender, profile_image FROM users ORDER BY id DESC")
        users_list = cur.fetchall()
        cur.close()
        conn.close()
        return users_list if users_list else []
    except Exception as e:
        print(f"Admin Kullanıcı listesi çekme hatası: {e}")
        return []