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
    Fungsi RAG Search menggunakan dynamic keyword matching: menghubungkan ai harness ke chromadb untuk
    mengambil potongan pasal regulasi resmi secara detail
    """
    try:
        # 1. Menghubungkan HTTP Client ke container ChromaDB
        client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
        collection = client.get_or_create_collection(name=COLLECTION_NAME)

        if collection.count() == 0:
            return "[Konteks RAG]: Database Regulasi ChromaDB belum terisi dokumen."
        try:   
            # 2. Eksekusi pencarian kemiripan vektor di ChromaDB
            results = collection.query(
                query_texts=[query_text],
                n_results=n_results
            )
            documents = results.get('documents', [[]])[0]
            metadatas = results.get('metadatas', [[]])[0]
        except Exception:
             # Dynamic Keyword Search Fallback
            all_chunks = collection.get( include=['documents','metadatas'])
            all_docs = all_chunks.get('documents',[])
            all_metas = all_chunks.get('metadatas', [])

            keywords = [kw.lower() for kw in query_text.split() if len(kw) > 2]

            scored_docs = []
            for doc, meta in zip(all_docs, all_metas):
                doc_lower = doc.lower()
                score = sum(1 for kw in keywords if kw in doc_lower)
                scored_docs.append((score, doc, meta))
            
            scored_docs.sort(key=lambda x: x[0], reverse=True)

            documents = [item[1] for item in scored_docs[:n_results]]
            metadatas = [item[2] for item in scored_docs[:n_results]]

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