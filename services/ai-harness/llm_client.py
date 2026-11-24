import json
import os
import re
import httpx
from openai import OpenAI
from dotenv import load_dotenv

# Membaca variabel lingkungan dari .env (Rule #8)
load_dotenv()

# Mengimpor RAG Client ChromaDB
from rag_client import query_rag_regulations

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")

# Fail-Fast Validation (Rule #8): Crash jika API Key belum diisi
if not LLM_API_KEY or "ganti" in LLM_API_KEY.lower() or LLM_API_KEY.strip() == "":
    print("[FATAL ERROR] LLM_API_KEY belum diisi dengan benar di file /root/balmon-sfr/.env!")


# DEFINISI TOOL AGENTIC RAG (Fungsi Pencarian ChromaDB yang Dipanggil DeepSeek)
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "query_rag_regulations",
            "description": "Mencari pasal/ayat regulasi spektrum frekuensi radio FM di ChromaDB berdasarkan kata kunci spesifik.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query_text": {
                        "type": "string",
                        "description": "Kata kunci pencarian regulasi, misal: 'Batas OBW FM' atau 'Kanal frekuensi Kota Batu Permen 5/2023'"
                    }
                },
                "required": ["query_text"]
            }
        }
    }
]


def clean_reasoning_and_markers(text: str) -> str:
    """Membersihkan teks pengantar agar hanya menyisakan Laporan Resmi murni"""
    if not text:
        return ""
    # Hapus tag <think> jika ada
    cleaned = re.sub(r'<think>.*?(?:</think>|$)', '', text, flags=re.DOTALL).strip()
    
    # Ambil teks mulai dari Judul Utama Laporan
    match = re.search(r'(LAPORAN AUDIT TEKNIS SPEKTRUM FREKUENSI RADIO.*)', cleaned, flags=re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return cleaned


def generate_balmon_audit_analysis(stasiun_name, freq_master, data_13_kolom):
    """
    Melakukan Agentic RAG search ke ChromaDB dan mengirim parameter 13 kolom hasil 
    pengukuran ke DeepSeek API untuk menghasilkan Laporan Audit Resmi Balmon SFR.
    """
    try:
        # 1. Retrieval Konteks RAG Awal dari ChromaDB
        rag_query_initial = f"Pasal 16 parameter teknis bandwidth 300 kHz deviasi 75 kHz FM {freq_master} MHz"
        rag_context = query_rag_regulations(rag_query_initial, n_results=5)

        # Inisialisasi Klien OpenAI resmi mengarah ke DeepSeek API Endpoint
        http_client = httpx.Client(trust_env=False, timeout=60.0)
        client = OpenAI(
            base_url=LLM_BASE_URL,
            api_key=LLM_API_KEY,
            http_client=http_client
        )

        system_prompt = f"""
Anda adalah Sistem Pakar Auditor Spektrum Frekuensi Radio (Balmon SFR) Kementerian Komunikasi dan Digital RI.

KONTEKS REGULASI HUKUM RESMI (DARI CHROMADB):
{rag_context}

INSTRUKSI WAJIB:
1. DILARANG menggunakan tanda pagar (#) untuk judul atau subjudul.
2. DILARANG menggunakan emotikon / emoji apapun.
3. DILARANG menuliskan kata pengantar, pembuka, atau proses berpikir.
4. ANDA WAJIB MENGISI TEMPLATE LAPORAN DINAS RESMI DI BAWAH INI SECARA PERSIS:

LAPORAN AUDIT TEKNIS SPEKTRUM FREKUENSI RADIO
Balai Monitor Spektrum Frekuensi Radio Kelas I Surabaya
======================================================

I. IDENTITAS STASIUN & PENGUKURAN
- Nama Stasiun Radio : {stasiun_name}
- Frekuensi Master   : {freq_master} MHz
- Channel Power      : {data_13_kolom.get('level_dbm')} dBm
- Occupied Bandwidth : {data_13_kolom.get('band_width_khz')} kHz
- Peak Deviasi FM    : {data_13_kolom.get('deviasi_khz')} kHz

II. TABEL EVALUASI KEPATUHAN TEKNIS
---------------------------------------------------------------------------------
Parameter Teknis         | Batas Regulasi       | Hasil Ukur  | Status Evaluasi
---------------------------------------------------------------------------------
Occupied Bandwidth (OBW) | Maksimal 300 kHz     | {data_13_kolom.get('band_width_khz')} kHz  | [Isi SESUAI jika <= 300 kHz, atau MELANGGAR]
Peak Deviasi FM          | Maksimal +/- 75 kHz  | {data_13_kolom.get('deviasi_khz')} kHz   | [Isi SESUAI jika <= 75 kHz, atau MELANGGAR]
Redaman Harmonisa H1-H3  | Pelemahan >= 60 dB   | H1={data_13_kolom.get('h1_db')} dB, H2={data_13_kolom.get('h2_db')} dB, H3={data_13_kolom.get('h3_db')} dB | [Isi SESUAI jika semua >= 60 dB, atau MELANGGAR]
---------------------------------------------------------------------------------

III. CATATAN & ANALISIS TEKNIS
(Tuliskan analisis teknis ringkas 2-3 kalimat mengenai kondisi pancaran frekuensi dan potensi gangguan interferensi)

IV. RUJUKAN HUKUM & REGULASI
1. Permen Kominfo No. 5/2023 Pasal 16 huruf a, b, c (Ketentuan Teknis Operasional Penyiaran Radio FM VHF Band II).
2. Kepmen Kominfo No. 570/2025 (Rencana Induk Penjatahan Kanal Frekuensi Radio FM).

V. REKOMENDASI OPERASIONAL
1. (Tindakan operasional prioritas 1)
2. (Tindakan operasional prioritas 2)

VI. KESIMPULAN AKHIR
STATUS KEPATUHAN : [Tuliskan SESUAI atau MELANGGAR]
Keterangan       : Stasiun radio {stasiun_name} ({freq_master} MHz) dinyatakan [SESUAI / MELANGGAR] terhadap standar teknis operasional penyiaran radio FM.
"""

        user_content = "Silakan isi template laporan dinas resmi di atas secara lengkap dan tepat berdasarkan data teknis!"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]

        print(f"[AI-Harness] Mengirim permintaan analisis ke DeepSeek API ({LLM_MODEL})...")

        # Eksekusi DeepSeek Chat Completion (Sangat Cepat & Presisi)
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            temperature=0.1,
            max_tokens=2500
        )

        raw_output = response.choices[0].message.content or ""
        final_clean_report = clean_reasoning_and_markers(raw_output)
        return final_clean_report

    except Exception as e:
        print(f"[AI-Harness Error] Error pada klien DeepSeek API: {e}")
        return f"Gagal mendapatkan respon dari DeepSeek API: {e}"
