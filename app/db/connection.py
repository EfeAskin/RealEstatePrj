import bcrypt
import psycopg2
from psycopg2 import pool as _pg_pool
import os
import threading
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

_pool = None
_pool_lock = threading.Lock()


def _get_pool():
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is not None:
            return _pool
        if not DATABASE_URL:
            print("CRITICAL: DATABASE_URL .env dosyasında bulunamadı!")
            return None
        try:
            _pool = _pg_pool.ThreadedConnectionPool(
                minconn=2,
                maxconn=20,
                dsn=DATABASE_URL,
                sslmode='require',
                # Oturum saat dilimini bağlantı anında ayarla; böylece her istekte
                # ayrı bir "SET TIME ZONE" gidiş-dönüşü (~0.17s) yapılmaz.
                options='-c timezone=Europe/Istanbul',
            )
        except Exception as e:
            print(f"CRITICAL: Veritabanı havuzu oluşturulamadı: {e}")
            _pool = None
        return _pool


class _PooledConnection:
    """Wraps a pooled psycopg2 connection so that .close() returns it to the
    pool instead of physically closing the socket. All other attributes/methods
    are delegated to the real connection."""

    __slots__ = ("_conn", "_pool", "_returned")

    def __init__(self, conn, pool):
        object.__setattr__(self, "_conn", conn)
        object.__setattr__(self, "_pool", pool)
        object.__setattr__(self, "_returned", False)

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def __setattr__(self, name, value):
        if name in ("_conn", "_pool", "_returned"):
            object.__setattr__(self, name, value)
        else:
            setattr(self._conn, name, value)

    def __enter__(self):
        return self._conn.__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        result = self._conn.__exit__(exc_type, exc_val, exc_tb)
        self.close()
        return result

    def __bool__(self):
        return True

    def close(self):
        if self._returned:
            return
        object.__setattr__(self, "_returned", True)
        try:
            if not self._conn.closed:
                try:
                    self._conn.rollback()
                except Exception:
                    pass
            self._pool.putconn(self._conn)
        except Exception as e:
            print(f"Havuz iade hatası: {e}")
            try:
                self._conn.close()
            except Exception:
                pass


def get_db_connection():
    """Neon PostgreSQL bağlantı havuzundan bir bağlantı verir.
    Dönen nesne üzerinde .close() çağrısı bağlantıyı havuza geri iade eder."""
    pool = _get_pool()
    if pool is None:
        return None
    try:
        raw = pool.getconn()
        return _PooledConnection(raw, pool)
    except Exception as e:
        print(f"CRITICAL: Havuzdan bağlantı alınamadı: {e}")
        return None


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


current_user_email = None
current_user_role = "guest"
current_user_data = {}
