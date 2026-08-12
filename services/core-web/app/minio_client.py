import os
from minio import Minio
from minio.error import S3Error

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "127.0.0.1:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ROOT_USER", "admin")
MINIO_SECRET_KEY = os.getenv("MINIO_ROOT_PASSWORD", "admin12345")
BUCKET_NAME = "balmon-measurements"

def get_minio_client():
    return Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=False
    )

def ensure_bucket_exists():
    """
    memastikan bucket 'balmon-measurements' sudah terbuat di MinIO
    """
    try:
        client = get_minio_client()
        if not client.bucket_exists(BUCKET_NAME):
            client.make_bucket(BUCKET_NAME)
            print(f"MinIO Bucket '{BUCKET_NAME}' berhasil dibuat.")
    except Exception as e:
        print(f" WARNING MinIO CONNECTION: {e}")

def upload_file_to_minio(file_storage, object_name):
    """
    Mengunggah file dari Flask Request ke MinIO
    """
    try:
        client = get_minio_client()
        ensure_bucket_exists()

        #baca ukuran file
        file_storage.seek(0, os.SEEK_END)
        file_length = file_storage.tell()
        file_storage.seek(0)

        client.put_object(
            BUCKET_NAME,
            object_name,
            file_storage,
            length=file_length,
            content_type=file_storage.content_type or "application/octet-stream"
        )
        print(f"File {object_name} berhasil di-upload ke MinIO.")
        return f"{BUCKET_NAME}/{object_name}"
    except S3Error as err:
        print(f"ERROR MinIO UPLOAD: {err} !")
        return None