import os
import sys
import psycopg2
from rq import Worker, Queue
import redis
from dotenv import load_dotenv

# Membaca variabel dari .env
load_dotenv()

from llm_client import generate_balmon_audit_analysis

REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
DB_HOST = os.getenv("POSTGRES_HOST", os.getenv("DB_HOST", "127.0.0.1"))
DB_NAME = os.getenv("POSTGRES_DB", os.getenv("DB_NAME", "balmon_spectra"))
DB_USER = os.getenv("POSTGRES_USER", os.getenv("DB_USER", "postgres"))
DB_PASS = os.getenv("POSTGRES_PASSWORD", os.getenv("DB_PASSWORD", "postgres12345"))
DB_PORT = os.getenv("POSTGRES_PORT", os.getenv("DB_PORT", "5432"))


def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS, port=DB_PORT
    )


def process_llm_analysis_job(session_uuid):
    """Job Worker: Membaca parameter 13 kolom & Mengirim ke Local LLM"""
    print(f"🤖 [AI-Harness Worker] Memulai Analisis LLM untuk Sesi: {session_uuid}")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Update status sesi menjadi 'analyzing'
        cursor.execute("UPDATE measurement_session SET status = 'analyzing' WHERE session_uuid = %s", (session_uuid,))
        conn.commit()

        # 1. Ambil data stasiun & parameter 13 kolom terbaru dari PostgreSQL
        cursor.execute("""
            SELECT r.nama_stasiun, r.frekuensi_mhz, h.level_dbm, h.band_width_khz, h.deviasi_khz,
                   h.h1_mhz, h.h1_dbm, h.h1_db, h.h2_mhz, h.h2_dbm, h.h2_db, h.h3_mhz, h.h3_dbm, h.h3_db, h.id
            FROM measurement_session s
            JOIN stasiun_radio r ON s.stasiun_id = r.id
            JOIN hasil_pengukuran h ON h.stasiun_id = r.id
            WHERE s.session_uuid = %s
            ORDER BY h.id DESC LIMIT 1
        """, (session_uuid,))
        
        row = cursor.fetchone()
        if not row:
            print(f"❌ Data pengukuran untuk sesi {session_uuid} tidak ditemukan.")
            return

        stasiun_name = row[0]
        freq_master = row[1]
        data_13_kolom = {
            'level_dbm': row[2], 'band_width_khz': row[3], 'deviasi_khz': row[4],
            'h1_mhz': row[5], 'h1_dbm': row[6], 'h1_db': row[7],
            'h2_mhz': row[8], 'h2_dbm': row[9], 'h2_db': row[10],
            'h3_mhz': row[11], 'h3_dbm': row[12], 'h3_db': row[13]
        }
        hasil_id = row[14]

        # 2. Panggil Klien Local LLM
        hasil_analisis_llm = generate_balmon_audit_analysis(stasiun_name, freq_master, data_13_kolom)

        # 3. Simpan Hasil Kesimpulan LLM ke PostgreSQL
        cursor.execute("""
            UPDATE hasil_pengukuran 
            SET catatan_llm = %s 
            WHERE id = %s
        """, (hasil_analisis_llm, hasil_id))

        # Update status sesi menjadi 'completed'
        cursor.execute("UPDATE measurement_session SET status = 'completed' WHERE session_uuid = %s", (session_uuid,))
        conn.commit()

        print(f"✅ [AI-Harness Worker] Selesai Analisis LLM untuk Sesi {session_uuid}!")

    except Exception as err:
        conn.rollback()
        cursor.execute("UPDATE measurement_session SET status = 'error_llm' WHERE session_uuid = %s", (session_uuid,))
        conn.commit()
        print(f"❌ Error pada AI-Harness Worker Job {session_uuid}: {err}")
    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    redis_conn = redis.from_url(REDIS_URL)
    worker = Worker(['llm_tasks'], connection=redis_conn)
    print("⚡ AI Harness Worker (LM Studio Local LLM) siap mendengarkan antrean 'llm_tasks'...")
    worker.work()
