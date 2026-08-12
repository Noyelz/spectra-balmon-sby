import json
import os
import numpy as np
import chromadb
from dotenv import load_dotenv

#membaca variable dari file .env
load_dotenv()

CHROMA_HOST = os.getenv("CHROMA_HOST", "127.0.0.1")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
COLLECTION_NAME = "balmon_regulations"

# path file
EMBEDDINGS_PATHS = [
    "rag/embeddings.npy",
    "rag/embeddings_kepmen570.npy",
]

CHUNK_INDEX_PATHS = [
    "rag/chunk_index.json",
    "rag/chunk_index_kepmen570.json",
]

def flatten_metadata(meta: dict) -> dict:
    """
    merapikan metadata agar kompatibel dengan format penyimpanan chromadb
    """

    flat = {}
    for k, v in meta.items():
        if v is None:
            continue
        if isinstance(v, (list, dict)):
            flat[k] = json.dumps(v, ensure_ascii=False)
        else:
            flat[k] = v
    return flat

def ingest_rag_to_chromadb():
    print(f"Memulai import data RAG Regulasi ke ChromaDB ({CHROMA_HOST}:{CHROMA_PORT})...")

    all_chunk_index = []
    all_embeddings_list = []

    # 1. membuat seluruh file vector .npy dan file teks metadata .json
    for emb_path, idx_path in zip(EMBEDDINGS_PATHS, CHUNK_INDEX_PATHS):
        if not os.path.exists(emb_path) or not os.path.exists(idx_path):
            print(f"File tidak ditemukan: {emb_path} atau {idx_path}")
            continue

        emb = np.load(emb_path, allow_pickle=True)
        emb = np.array(emb, dtype=np.float32)
        idx = json.load(open(idx_path, encoding="utf-8"))

        assert emb.shape[0] == len(idx), f"Error: Jumlah embedding dan metadata tidak selaras di {emb_path}!"

        all_embeddings_list.append(emb)
        all_chunk_index.extend(idx)
        print(f"Dimuat: {emb_path} ({emb.shape[0]} chunk regulasi)")

    if not all_embeddings_list:
        print("Gagal: Tidak ada file embedding yang ditemukan di folder rag/.")
        return

    embeddings = np.vstack(all_embeddings_list)
    print(f"Total gabungan: {embeddings.shape[0]} chunk regulasi resmi, dimensi vektor: {embeddings.shape[1]}")

    # 2. menghubungkan ke chromadb container dan mengunggah data
    try:
        client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
        # Reset koleksi balmon_regulations agar bersih
        try:
            client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass
        collection = client.create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )
        ids = [c["chunk_id"] for c in all_chunk_index]
        documents = [c["text"] for c in all_chunk_index]
        metadatas = [flatten_metadata(c["metadata"]) for c in all_chunk_index]
        # Batch upload per 100 data
        batch_size = 100
        for i in range(0, len(ids), batch_size):
            end_idx = min(i + batch_size, len(ids))
            collection.add(
                ids=ids[i:end_idx],
                embeddings=embeddings[i:end_idx].tolist(),
                documents=documents[i:end_idx],
                metadatas=metadatas[i:end_idx]
            )
        print(f"SUKSES! Berhasil mengunggah {collection.count()} pasal dokumen regulasi resmi (Permen 5/2023 & Kepmen 570/2025) ke ChromaDB.")
    except Exception as err:
        print(f"GAGAL mengunggah data ke ChromaDB: {err}")
if __name__ == "__main__":
    ingest_rag_to_chromadb()
