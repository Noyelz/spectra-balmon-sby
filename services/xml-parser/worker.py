import os
import sys
import psycopg2
from minio import Minio
from rq import Worker, Queue
import redis
from dotenv import load_dotenv

# Membaca environment variables dari .env
load_dotenv()

from fmspa_parser import parse_obw_xml, parse_deviasi_xml, parse_harmonisa_xml

# Menggunakan Kredensial Asli dari .env
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
DB_HOST = os.getenv("POSTGRES_HOST", os.getenv("DB_HOST", "127.0.0.1"))
DB_NAME = os.getenv("POSTGRES_DB", os.getenv("DB_NAME", "balmon_spectra"))
DB_USER = os.getenv("POSTGRES_USER", os.getenv("DB_USER", "postgres"))
DB_PASS = os.getenv("POSTGRES_PASSWORD", os.getenv("DB_PASSWORD", "postgres12345"))
DB_PORT = os.getenv("POSTGRES_PORT", os.getenv("DB_PORT", "5432"))

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "127.0.0.1:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ROOT_USER", "admin")
MINIO_SECRET_KEY = os.getenv("MINIO_ROOT_PASSWORD", "admin12345")
BUCKET_NAME = "balmon-measurements"


def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS, port=DB_PORT
    )

def get_minio_client():
    return Minio(MINIO_ENDPOINT, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=False)


def process_xml_parsing_job(session_uuid):
    """Job Worker: Parse XML & Melakukan Cross-Check Frekuensi"""
    print(f"🚀 [Worker] Memulai parsing & cross-check untuk Sesi: {session_uuid}")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 1. Ambil info path file & frekuensi master stasiun radio dari PostgreSQL
        cursor.execute("""
            SELECT s.id, s.stasiun_id, s.obw_fmspa_path, s.deviasi_fmspa_path, s.harmonisa_fmspa_path, r.frekuensi_mhz, r.nama_stasiun
            FROM measurement_session s
            JOIN stasiun_radio r ON s.stasiun_id = r.id
            WHERE s.session_uuid = %s
        """, (session_uuid,))
        
        row = cursor.fetchone()
        if not row:
            print(f"❌ Sesi {session_uuid} tidak ditemukan.")
            return

        session_id, stasiun_id, obw_path, dev_path, har_path, master_freq_mhz, nama_stasiun = row

        cursor.execute("UPDATE measurement_session SET status = 'parsing' WHERE id = %s", (session_id,))
        conn.commit()

        # 2. Unduh 3 file dari MinIO
        minio_client = get_minio_client()
        obw_obj_name = obw_path.replace(f"{BUCKET_NAME}/", "")
        dev_obj_name = dev_path.replace(f"{BUCKET_NAME}/", "")
        har_obj_name = har_path.replace(f"{BUCKET_NAME}/", "")

        obw_bytes = minio_client.get_object(BUCKET_NAME, obw_obj_name).read()
        dev_bytes = minio_client.get_object(BUCKET_NAME, dev_obj_name).read()
        har_bytes = minio_client.get_object(BUCKET_NAME, har_obj_name).read()

        # 3. Jalankan Parser XML
        bw_khz, level_dbm, freq_terukur_mhz = parse_obw_xml(obw_bytes)
        deviasi_khz = parse_deviasi_xml(dev_bytes)
        harmonisa = parse_harmonisa_xml(har_bytes, level_dbm)

        # 4. LOGIKA CROSS-CHECK FREKUENSI (Master DB vs File .fmspa)
        selisih_freq = abs(freq_terukur_mhz - master_freq_mhz)
        is_matched = selisih_freq <= 0.5  # Toleransi 0.5 MHz

        if is_matched:
            final_status = 'parsed'
            ket_crosscheck = f"Valid: Frekuensi file ({freq_terukur_mhz} MHz) COCOK dengan master {nama_stasiun} ({master_freq_mhz} MHz)."
        else:
            final_status = 'warning_mismatch'
            ket_crosscheck = f"PERINGATAN: Frekuensi file ({freq_terukur_mhz} MHz) BEDA dengan master {nama_stasiun} ({master_freq_mhz} MHz)!"

        # 5. Simpan Hasil ke PostgreSQL hasil_pengukuran
        cursor.execute("""
            INSERT INTO hasil_pengukuran (
                stasiun_id, tanggal_pengukuran, level_dbm, band_width_khz, deviasi_khz,
                h1_mhz, h1_dbm, h1_db, h2_mhz, h2_dbm, h2_db, h3_mhz, h3_dbm, h3_db, keterangan
            ) VALUES (
                %s, CURRENT_DATE, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
        """, (
            stasiun_id, level_dbm, bw_khz, deviasi_khz,
            harmonisa['h1_mhz'], harmonisa['h1_dbm'], harmonisa['h1_db'],
            harmonisa['h2_mhz'], harmonisa['h2_dbm'], harmonisa['h2_db'],
            harmonisa['h3_mhz'], harmonisa['h3_dbm'], harmonisa['h3_db'],
            ket_crosscheck
        ))

        # Update status di measurement_session
        cursor.execute("UPDATE measurement_session SET status = %s WHERE id = %s", (final_status, session_id))
        conn.commit()

        print(f"✅ [Worker] Selesai parsing {session_uuid}! Status: {final_status}. {ket_crosscheck}")

    except Exception as err:
        conn.rollback()
        cursor.execute("UPDATE measurement_session SET status = 'error_parsing' WHERE session_uuid = %s", (session_uuid,))
        conn.commit()
        print(f"❌ Error pada Worker Job {session_uuid}: {err}")
    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    redis_conn = redis.from_url(REDIS_URL)
    worker = Worker(['parse_xml_tasks'], connection=redis_conn)
    print("⚡ XML Parser Worker siap mendengarkan antrean 'parse_xml_tasks'...")
    worker.work()
