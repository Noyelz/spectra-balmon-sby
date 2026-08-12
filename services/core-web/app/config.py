# modul bawaan python untuk membaca variable lingkungan seperti
# .env
import os
# modul import untuk menghentikan aplikasi secara paksa
# contoh (sys.exit(1)) jika tidak ditemukan .env
import sys
# library resmi dari postgres untuk membuat koneksi langsung
# dengan postgres sebelum sqlalchemy di nyalakan
import psycopg2 
# mengimpor konstanta ISOLATON_LEVEL_AUTOCOMMIT di postgress. 
# karena create database tida boleh berlajallan dalam transaksi
# sql biasa, jadi kita pakai level auto commit
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from dotenv import load_dotenv

# membaca rahasia dari file .env 
load_dotenv()

class Config:
#mengambil pass database di sesuaikan untuk docker
    DB_USER = os.getenv("POSTGRES_USER")
    DB_PASS = os.getenv("POSTGRES_PASSWORD")
    DB_HOST = os.getenv("POSTGRES_HOST", "127.0.0.1")
    DB_PORT = os.getenv("POSTGRES_PORT", "5432")
    DB_NAME = os.getenv("POSTGRES_DB", "balmon_spectra")

    # Validasi environment varables (fail-fast)
    REQUIRED_VARS = ["POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"]
    missing = [var for var in REQUIRED_VARS if not os.getenv(var)]
    if missing:
        print(f"FATAL ERROR: Variabel environment berikut belum diisi di .env: {', '.join(missing)}")
        sys.exit(1)

    SECRET_KEY = os.getenv("SECRET_KEY", os.getenv("SECRETE_KEY", "balmon-sfr-secret-key-1234567890"))

    # sqlalchemy tetap di pakai unutk koneksi utama yang dipakai oleh flask-sqlalchemy
    SQLALCHEMY_DATABASE_URI = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

def ensure_database_exists():
    """
    memastikan kalau database balmon_spectra sudah ada di postgres
    """
    try:
        conn = psycopg2.connect(
            dbname='postgres',
            user=Config.DB_USER,
            password=Config.DB_PASS,
            host=Config.DB_HOST,
            port=Config.DB_PORT
        )
    
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)

        cursor = conn.cursor()

        cursor.execute("SELECT 1 FROM pg_catalog.pg_database where datname = %s;", (Config.DB_NAME,))
        exists = cursor.fetchone()

        if not exists:
            print(f"Database '{Config.DB_NAME}' belum ada. Membuatkan database baru...")
            cursor.execute(f'CREATE DATABASE "{Config.DB_NAME}";')
            print(f"Database '{Config.DB_NAME}' berhasil dibuatkan.")
        else:
            print(f"Database '{Config.DB_NAME}' sudah ada. Lanjut")
            
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"GAGAL MENGECEK/MEMBUAT DATABASE: {e}")

            