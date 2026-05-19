import bcrypt
import psycopg2
import os
import time
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

# --- GENEL SORGÜ CLARIŞTIRICI ---
def execute_query(query, params=None):
    """Veritabanında INSERT, UPDATE, DELETE gibi işlemleri yapmak için genel yardımcı"""
    conn = get_db_connection()
    if not conn: return False
    try:
        cur = conn.cursor()
        cur.execute(query, params)
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Sorgu yürütme hatası: {e}")
        if conn: conn.rollback()
        return False

# --- ŞİFRELEME FONKSiyonLARI ---
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