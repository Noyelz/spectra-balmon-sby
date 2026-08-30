import json
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

# DEFINISI TOOL AGENTIC RAG (Fungsi Pencarian ChromaDB yang Bisa Dipanggil AI)
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

def generate_balmon_audit_analysis(stasiun_name, freq_master, data_13_kolom):
    """
    Melakukan Rag search ke chromadb dan mengirim parameter 13 kolom hasil 
    pengukuran ke lm studio (local llm) untuk analisis kesimpulan hukum teknis.
    """
    try:
        rag_query_initial = f"Pasal 16 parameter teknis bandwidth 300 kHz deviasi 75 kHz FM {freq_master} MHz"
        rag_context = query_rag_regulations(rag_query_initial, n_results=7)

        # Inisialisasi Klien OpenAI yang mengarah ke IP LM Studio Local
        http_client = httpx.Client(trust_env=False, timeout=600.0)
        client = OpenAI(
            base_url=LLM_BASE_URL,
            api_key=LLM_API_KEY,
            http_client=http_client
        )

        target_model = get_active_model_name(client)

        system_prompt = f"""
Anda adalah Sistem Pakar Auditor Spektrum Frekuensi Radio (Balmon SFR) Kementerian Komunikasi dan Digital RI.
Tugas Anda:
1. Analisis data hasil pengukuran spectrum analyzer stasiun radio FM {stasiun_name} (Frekuensi {freq_master} MHz, Wilayah {data_13_kolom.get('kab_kota', 'Jawa Timur')}).
2. ANDA WAJIB MENCARI SENDIRI pasal regulasi yang relevan di ChromaDB menggunakan tool `query_rag_regulations`.
   - Cari standar batas toleransi OBW dan Deviasi FM.
   - Cari alokasi kanal frekuensi resmi untuk wilayah tersebut.
3. Setelah mendapatkan pasal-pasal dari ChromaDB, susun laporan audit resmi mencakup:
   - Status Kepatuhan Teknis (Sesuai / Melanggar)
   - Catatan Penyimpangan Parameter (jika ada)
   - Referensi Regulasi Hukum yang Dilanggar / Dipatuhi (HANYA dari ChromaDB)
   - Rekomendasi Tindakan Operasional Balmon
Instruksi Tambahan:
- Langsung berikan hasil analisis tanpa menuliskan ulang proses berpikir internal Anda.
Berikan jawaban profesional ringkas mencakup:
- Status Kepatuhan Teknis (Sesuai / Melanggar)
- Catatan Penyimpangan Parameter (jika ada)
- Referensi Regulasi Hukum yang Dilanggar / Dipatuhi
- Rekomendasi Tindakan Operasional Balmon
- WAJIB HANYA mengutip pasal/regulasi yang tercantum di dalam KONTEKS REGULASI HUKUM RELEVAN (DARI RAG VECTOR DATABASE CHROMADB). DILARANG mengutip Undang-Undang atau peraturan luar yang tidak ada di dalam konteks RAG yang diberikan.
- DILARANG melakukan proses berpikir internal yang panjang. Langsung berikan hasil analisis secara ringkas dan cepat.
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
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]
        collected_rag_contexts = [rag_context]
        # LOOP AGENTIC RAG (Maksimal 3x Putaran untuk Self-Correction & Re-Checking ke ChromaDB)
        for turn in range(3):
            try:
                response = client.chat.completions.create(
                    model=target_model,
                    messages=messages,
                    tools=TOOLS_SCHEMA,
                    tool_choice="auto",
                    temperature=0.3,
                    max_tokens=6400
                )
            except Exception:
                # Fallback jika model LM Studio tidak mendukung fitur Tool-Use
                response = client.chat.completions.create(
                    model=target_model,
                    messages=messages,
                    temperature=0.3,
                    max_tokens=6400
                )
            choice_message = response.choices[0].message
            messages.append(choice_message)
            # Cek apakah AI meminta pencarian pasal RAG tambahan (Tool Call)?
            if getattr(choice_message, 'tool_calls', None):
                for tool_call in choice_message.tool_calls:
                    if tool_call.function.name == "query_rag_regulations":
                        try:
                            args = json.loads(tool_call.function.arguments)
                            search_keyword = args.get("query_text", "")
                        except Exception:
                            search_keyword = rag_query_initial
                        print(f"[Agentic RAG Turn {turn+1}] AI mengecek kembali ChromaDB dengan kata kunci: '{search_keyword}'")
                        additional_context = query_rag_regulations(search_keyword, n_results=2)
                        if additional_context not in collected_rag_contexts:
                            collected_rag_contexts.append(additional_context)

                        # Mengembalikan hasil pencarian pasal baru ke AI
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": additional_context
                        })
            else:
                # Jika AI tidak memanggil tool lagi, berarti AI sudah yakin dengan pasal yang dipegang
                break
        final_content = choice_message.content or ""
        if not final_content.strip() and hasattr(choice_message, 'reasoning_content') and choice_message.reasoning_content:
            final_content = choice_message.reasoning_content
        all_rag_str = "\n\n".join(collected_rag_contexts)
        return f"**DOKUMEN PASAL REGULASI HASIL AGENTIC RAG SEARCH (CHROMADB):**\n{all_rag_str}\n\n=======================================================\n\n{final_content}"
    except Exception as e:
        print(f"ERROR PADA KLIEN AGENTIC LLM: {e}")
        return f"Gagal mendapatkan respon dari Agentic Local LLM: {e}"