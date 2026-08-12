import os
import httpx
from openai import OpenAI
from dotenv import load_dotenv

# Membaca variabel lingkungan dari .env
load_dotenv()

# Mengimpor RAG Client
from rag_client import query_rag_regulations

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://100.106.232.117:1234/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "sk-lm-lWsR5WHf:Lu7i76BWbYYC7oJnsVqn")
LLM_MODEL = os.getenv("LLM_MODEL", "local-model")


def get_active_model_name(client):
    """Mendeteksi nama model yang sedang di-load aktif di LM Studio"""
    try:
        models = client.models.list()
        if models and models.data:
            # Ambil model pertama yang tersedia di LM Studio
            active_model = models.data[0].id
            print(f"Model LM Studio terdeteksi: {active_model}")
            return active_model
    except Exception as e:
        print(f"!GAGAL MENDETEKSI MODEL LM Studio: {e}")
    return LLM_MODEL


def generate_balmon_audit_analysis(stasiun_name, freq_master, data_13_kolom):
    """
    Melakukan Rag search ke chromadb dan mengirim parameter 13 kolom hasil 
    pengukuran ke lm studio (local llm) untuk analisis kesimpulan hukum teknis.
    """
    try:
        #1 menyiapkan kuery rag vektor berdasarkan parameter ukur
        rag_query = f"Standar batas toleransi frekuensi FM {freq_master} Mhz deviasi {data_13_kolom.get('deviasi_khz')} kHz bandwidth OBW {data_13_kolom.get('band_width_khz')} kHz attenuasi harmonisa"
        
        #2 mengambil konteks regulasi relevan dari chromadb
        rag_context = query_rag_regulations(rag_query, n_results=3)

        # Inisialisasi Klien OpenAI yang mengarah ke IP LM Studio Local
        http_client = httpx.Client(trust_env=False, timeout=120.0)
        client = OpenAI(
            base_url=LLM_BASE_URL,
            api_key=LLM_API_KEY,
            http_client=http_client
        )

        target_model = get_active_model_name(client)

        system_prompt = f"""
Anda adalah Sistem Pakar Auditor Spektrum Frekuensi Radio (Balmon SFR) Kementerian Komunikasi dan Digital RI.
Tugas Anda adalah melakukan verifikasi teknis dan analisis kepatuhan hukum atas hasil pengukuran spectrum analyzer stasiun radio FM.
Aturan Evaluasi Teknis:
1. Frekuensi Terukur vs Master: Toleransi pergeseran frekuensi carrier maksimal 0.5 MHz.
2. Peak Deviasi: Standar maksimal deviasi FM adalah 75.0 kHz (PMKG / Perdirjen SDPPI).
3. Bandwidth (OBW): Standar lebar pita FM adalah 200.0 kHz.
4. Attenuasi Harmonisa (H1, H2, H3): Nilai relatif H(dB) = |Level_dBm - H_dBm| idealnya >= 40 dB atau sesuai ketentuan teknis.
KONTEKS REGULASI HUKUM RELEVAN (DARI RAG VECTOR DATABASE CHROMADB):
{rag_context}
Instruksi Tambahan:
- Langsung berikan hasil analisis tanpa menuliskan ulang proses berpikir internal Anda.
Berikan jawaban profesional ringkas mencakup:
- Status Kepatuhan Teknis (Sesuai / Melanggar)
- Catatan Penyimpangan Parameter (jika ada)
- Referensi Regulasi Hukum yang Dilanggar / Dipatuhi
- Rekomendasi Tindakan Operasional Balmon
- WAJIB HANYA mengutip pasal/regulasi yang tercantum di dalam KONTEKS REGULASI HUKUM RELEVAN (DARI RAG VECTOR DATABASE CHROMADB). DILARANG mengutip Undang-Undang atau peraturan luar yang tidak ada di dalam konteks RAG yang diberikan.
"""

        user_content = f"""
RINCIAN DATA HASIL PENGUKURAN SPECTRUM ANALYZER:
- Nama Stasiun Radio: {stasiun_name}
- Frekuensi Master Terdaftar: {freq_master} MHz
- Channel Power / Level: {data_13_kolom.get('level_dbm')} dBm
- Occupied Bandwidth (OBW): {data_13_kolom.get('band_width_khz')} KHz
- Peak Deviasi FM: {data_13_kolom.get('deviasi_khz')} KHz
DATA HARMONISA RELATIF:
- Harmonisa H1: {data_13_kolom.get('h1_mhz')} MHz | Level: {data_13_kolom.get('h1_dbm')} dBm | Attenuasi: {data_13_kolom.get('h1_db')} dB
- Harmonisa H2: {data_13_kolom.get('h2_mhz')} MHz | Level: {data_13_kolom.get('h2_dbm')} dBm | Attenuasi: {data_13_kolom.get('h2_db')} dB
- Harmonisa H3: {data_13_kolom.get('h3_mhz')} MHz | Level: {data_13_kolom.get('h3_dbm')} dBm | Attenuasi: {data_13_kolom.get('h3_db')} dB
Silakan berikan analisis audit teknis dan rekomendasi secara lengkap!
"""
        # token di naikkan (jangan 1000 untuk thinking model)
        response = client.chat.completions.create(
            model=target_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            temperature=0.3,
            max_tokens=6400
        )

        choice_message = response.choices[0].message
        content = choice_message.content or ""

        # fallback jika 'content' kosong tapi ada 'reasoning content'

        if not content.strip() and hasattr(choice_message, 'reasoning_content') and choice_message.reasoning_content:
            content = choice_message.reasoning_content

        return content

    except Exception as e:
        print(f"ERROR saat memanggil Local LLM (LM Studio): {e}")
        return f"Gagal mendapatkan respon dari AI LLM: {e}"
