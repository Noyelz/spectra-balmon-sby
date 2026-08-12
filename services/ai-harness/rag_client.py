import os
import chromadb
from dotenv import load_dotenv

# membaca variable dari file .env
load_dotenv()

CHROMA_HOST = os.getenv("CHROMA_HOST", "127.0.0.1")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
COLLECTION_NAME = "balmon_regulations"
def query_rag_regulations(query_text, n_results=3):
    """
    Fungsi RAG Search: Menghubungkan AI Harness ke ChromaDB untuk mengambil 
    potongan pasal regulasi resmi (Permen 5/2023 & Kepmen 570/2025).
    """
    try:
        # 1. Menghubungkan HTTP Client ke container ChromaDB
        client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
        collection = client.get_or_create_collection(name=COLLECTION_NAME)
        if collection.count() == 0:
            return "[Konteks RAG]: Database Regulasi ChromaDB belum terisi dokumen."
        # 2. Eksekusi pencarian kemiripan vektor di ChromaDB
        results = collection.query(
            query_texts=[query_text],
            n_results=n_results
        )
        documents = results.get('documents', [[]])[0]
        metadatas = results.get('metadatas', [[]])[0]
        if not documents:
            return "[Konteks RAG]: Tidak ditemukan pasal spesifik yang cocok di ChromaDB."
        # 3. Merapi-rapi pasal regulasi yang ditemukan
        context_blocks = []
        for idx, doc in enumerate(documents):
            meta = metadatas[idx] if idx < len(metadatas) else {}
            # Membaca nama dokumen dari metadata
            nama_regulasi = meta.get('dokumen', meta.get('nama_regulasi', 'Regulasi Balmon'))
            halaman = meta.get('halaman', '-')
            context_blocks.append(f"--- [Referensi {idx+1}: {nama_regulasi} (Halaman {halaman})] ---\n{doc}")
        print(f"[RAG Search] Berhasil mengambil {len(documents)} pasal regulasi relevan dari ChromaDB!")
        return "\n\n".join(context_blocks)
    except Exception as err:
        print(f"[RAG Warning] Gagal terhubung ke ChromaDB: {err}")
        return "[Konteks RAG]: ChromaDB tidak terjangkau. Menggunakan acuan standar umum."