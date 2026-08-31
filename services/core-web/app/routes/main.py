import os
import uuid
import chromadb
import httpx
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file
from app import db
from app.models.radio import StasiunRadio
from app.models.session import MeasurementSession
from app.minio_client import upload_file_to_minio, get_minio_client, BUCKET_NAME
from app.export_helper import generate_word_report, generate_pdf_report
from sqlalchemy import text
from redis import Redis
from rq import Queue, Worker


# Blueprint itu seperti kumpulan rute. nantinya akan di registrasikan di file app utama.
main_bp = Blueprint('main', __name__)

# Fungsi bantuan untuk mengambil daftar unik Kab/kota dan sub servis dari database
def get_dropdown_options():
    kab_kota_rows = db.session.query(StasiunRadio.kab_kota).distinct().all()
    sub_servis_rows = db.session.query(StasiunRadio.sub_servis).filter(StasiunRadio.sub_servis.isnot(None)).distinct().all()
    
    kab_kota_options = [r[0] for r in kab_kota_rows if r[0]]
    sub_servis_options =[r[0] for r in sub_servis_rows if r[0]]

    return kab_kota_options, sub_servis_options

@main_bp.route('/')
@main_bp.route('/dashboard')
def dashboard():
    """Halaman Dashboard Utama dengan Live Health Check seluruh service"""
    health = {}
    metrics = {}

    # 1. Metrik Total Data
    try:
        metrics['total_stasiun'] = StasiunRadio.query.count()
        metrics['total_sesi'] = MeasurementSession.query.count()
        metrics['total_selesai_ai'] = MeasurementSession.query.filter_by(status='completed').count()
    except Exception:
        metrics['total_stasiun'] = 0
        metrics['total_sesi'] = 0
        metrics['total_selesai_ai'] = 0

    # 2. Cek Kesehatan PostgreSQL
    try:
        db.session.execute(text('SELECT 1'))
        health['postgres'] = {"status": "Online", "color": "green", "detail": "balmon_spectra (Port 5432)"}
    except Exception as e:
        health['postgres'] = {"status": "Offline", "color": "red", "detail": str(e)[:30]}

    # 3. Cek Kesehatan Redis & Antrean RQ
    REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    try:
        r_conn = Redis.from_url(REDIS_URL)
        r_conn.ping()
        workers = Worker.all(connection=r_conn)
        q_xml = Queue('parse_xml_tasks', connection=r_conn)
        q_llm = Queue('llm_tasks', connection=r_conn)
        health['redis'] = {
            "status": "Online",
            "color": "green",
            "detail": f"{len(workers)} Worker Aktif | Antrean XML: {len(q_xml)} | Antrean LLM: {len(q_llm)}"
        }
    except Exception as e:
        health['redis'] = {"status": "Offline", "color": "red", "detail": str(e)[:30]}

    # 4. Cek MinIO Object Storage
    try:
        m_client = get_minio_client()
        bucket_ready = m_client.bucket_exists(BUCKET_NAME)
        health['minio'] = {
            "status": "Online",
            "color": "green",
            "detail": f"Bucket '{BUCKET_NAME}' ({'Siap' if bucket_ready else 'Belum Ada'})"
        }
    except Exception as e:
        health['minio'] = {"status": "Offline", "color": "red", "detail": str(e)[:30]}

    # 5. Cek ChromaDB Vector Database
    CHROMA_HOST = os.getenv("CHROMA_HOST", "127.0.0.1")
    CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
    try:
        chroma_client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
        collection = chroma_client.get_or_create_collection("balmon_regulations")
        reg_count = collection.count()
        metrics['total_regulasi'] = reg_count
        health['chroma'] = {
            "status": "Online",
            "color": "green",
            "detail": f"{reg_count} Chunk Regulasi Dimuat"
        }
    except Exception as e:
        metrics['total_regulasi'] = 0
        health['chroma'] = {"status": "Offline", "color": "red", "detail": str(e)[:30]}

    # 6. Cek Local LLM (LM Studio)
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://100.106.232.117:1234/v1")
    try:
        resp = httpx.get(f"{LLM_BASE_URL}/models", timeout=3.0)
        if resp.status_code == 200:
            models_data = resp.json().get('data', [])
            model_name = models_data[0].get('id', 'Local LLM') if models_data else 'Aktif'
            health['llm'] = {"status": "Online", "color": "green", "detail": f"Model: {model_name[:22]}"}
        else:
            health['llm'] = {"status": "Warning", "color": "orange", "detail": f"Status HTTP {resp.status_code}"}
    except Exception:
        health['llm'] = {"status": "Offline", "color": "red", "detail": "LM Studio Tidak Terjangkau"}

    # 7. Cek Telegram Bot Token
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    if TELEGRAM_BOT_TOKEN and "token" not in TELEGRAM_BOT_TOKEN.lower():
        health['telegram'] = {"status": "Aktif", "color": "green", "detail": "@balmon_sby_bot"}
    else:
        health['telegram'] = {"status": "Belum Dikonfigurasi", "color": "orange", "detail": "Token Kosong di .env"}

    return render_template('dashboard.html', health=health, metrics=metrics)

# Jika user membuka URL '/daftar-radio', menjalankan fungsi ini
@main_bp.route('/daftar-radio', methods=['GET'])
def daftar_radio():
    stasiun_list = StasiunRadio.query.order_by(StasiunRadio.id.desc()).all()
    kab_kota_options, sub_servis_options = get_dropdown_options()
    return render_template(
        'daftar_radio.html',
        stasiun_list=stasiun_list,
        radio_edit=None,
        kab_kota_options=kab_kota_options,
        sub_servis_options=sub_servis_options
    )

# mode edit: mengambil data radio berdasarkan id untuk di load ke form
@main_bp.route('/daftar-radio/edit/<int:id>', methods=['GET'])
def edit_radio_view(id):
    stasiun_list = StasiunRadio.query.order_by(StasiunRadio.id.desc()).all()
    radio_edit = StasiunRadio.query.get_or_404(id)
    kab_kota_options, sub_servis_options = get_dropdown_options()
    return render_template(
        'daftar_radio.html',
        stasiun_list=stasiun_list,
        radio_edit=radio_edit,
        kab_kota_options=kab_kota_options,
        sub_servis_options=sub_servis_options
    )

# menambah stasiun radio baru (post)
@main_bp.route('/daftar-radio/tambah', methods=['POST'])
def tambah_radio():
    nama_penyelenggara = request.form.get('nama_penyelenggara')
    nama_stasiun = request.form.get('nama_stasiun')
    kab_kota = request.form.get('kab_kota')
    sub_servis = request.form.get('sub_servis')
    kanal = request.form.get('kanal')
    frekuensi_mhz = request.form.get('frekuensi_mhz')

    if nama_penyelenggara and nama_stasiun and kab_kota and frekuensi_mhz:
        radio_baru = StasiunRadio(
            nama_penyelenggara=nama_penyelenggara,
            nama_stasiun=nama_stasiun,
            kab_kota=kab_kota,
            sub_servis=sub_servis,
            kanal=kanal,
            frekuensi_mhz=float(frekuensi_mhz)
        )  
        db.session.add(radio_baru)
        db.session.commit()
    
    return redirect(url_for('main.daftar_radio'))

# menyimpan perubahan data radio (post update)
@main_bp.route('/daftar-radio/update/<int:id>', methods=['POST'])
def update_radio(id):
    radio = StasiunRadio.query.get_or_404(id)
    radio.nama_penyelenggara = request.form.get('nama_penyelenggara')
    radio.nama_stasiun = request.form.get('nama_stasiun')
    radio.kab_kota = request.form.get('kab_kota')
    radio.sub_servis = request.form.get('sub_servis')
    radio.kanal = request.form.get('kanal')
    frekuensi = request.form.get('frekuensi_mhz')
    if frekuensi:
        radio.frekuensi_mhz = float(frekuensi)
    
    db.session.commit()
    return redirect(url_for('main.daftar_radio'))

# menghapus data radio (POST Delete)
@main_bp.route('/daftar-radio/hapus/<int:id>', methods=['POST'])
def hapus_radio(id):
    radio = StasiunRadio.query.get_or_404(id)
    db.session.delete(radio)
    db.session.commit()

    return redirect(url_for('main.daftar_radio'))

# RUTE MODULE UPLOAD & SESI PENGUKURAN (6 FILE MINIO)

# 1. Halaman Khusus Form Upload File (.fmspa + gambar)
@main_bp.route('/upload-file', methods=['GET'])
def upload_file_view():
    # Mengambil master data stasiun radio untuk isi dropdown
    stasiun_list = StasiunRadio.query.order_by(StasiunRadio.nama_stasiun.asc()).all()
    return render_template('upload_file.html', stasiun_list=stasiun_list)

# 2. Halaman Daftar Riwayat Sesi Pengukuran & AI Harness
@main_bp.route('/sesi-pengukuran', methods=['GET'])
def sesi_pengukuran_view():
    # Mengambil seluruh riwayat sesi yang tersimpan di PostgreSQL
    sesi_list = MeasurementSession.query.order_by(MeasurementSession.id.desc()).all()
    return render_template('sesi_list.html', sesi_list=sesi_list)

# 2. api endpoint untuk ambil info stasiun saat dropdown dipilih (htmx)
@main_bp.route('/api/stasiun-detail/<int:id>', methods=['GET'])
@main_bp.route('/api/stasiun-detail/', methods=['GET'])
def stasiun_detail_api(id=None):
    if not id:
        id = request.args.get('stasiun_id', type=int)
    if not id:
        return ""
    stasiun = StasiunRadio.query.get_or_404(id)
    return f"""
    <div style="backgrouund: #f7f7f7; border: 1px solid var(--border-color); padding: 10px; margin-top: 10px; border-radius: 2px; font-size: 12px;">
        <strong>Detail Stasiuun Terpilih:</strong><br>
        • Penyelenggara: {stasiun.nama_penyelenggara}<br>
        • Kab/Kota: {stasiun.kab_kota} | Sub Servis: {stasiun.sub_servis or '-'} | Kanal: {stasiun.kanal or '-'}<br>
        • Frekuensi: <strong>{stasiun.frekuensi_mhz} MHz</strong>
    </div>"""

from redis import Redis
from rq import Queue
from app.models.radio import StasiunRadio, HasilPengukuran

# 3. memproses upload 6 file dan menyimpan sesi ke minio + db (post)
@main_bp.route('/sesi-pengukuran/upload', methods=['POST'])
def simpan_sesi_pengukuran():
    stasiun_id = request.form.get('stasiun_id')
    if not stasiun_id:
        return "<div style='color:red;'>Pilih Stasiun Radio terlebih dahulu!</div>", 400
    
    # ambil 6 file dari request form
    obw_fmspa = request.files.get('obw_fmspa')
    obw_img = request.files.get('obw_img')

    harmonisa_fmspa = request.files.get('harmonisa_fmspa')
    harmonisa_img = request.files.get('harmonisa_img')

    deviasi_fmspa = request.files.get('deviasi_fmspa')
    deviasi_img = request.files.get('deviasi_img')

    # validasi 6 file dan wajib di upload
    if not (obw_fmspa and obw_img and harmonisa_fmspa and harmonisa_img and deviasi_fmspa and deviasi_img):
        return "<div style='color:red;'>Seluruh 6 file (3 file .fmspa + 3 file gambar) WAJIB diunggah!</div>", 400

    # buat uuid sesi unik
    session_id = str(uuid.uuid4())

    # unggah ke-6 file ke MinIO
    path_obw_fmspa = upload_file_to_minio(obw_fmspa, f"{session_id}/obw/{obw_fmspa.filename}")
    path_obw_img = upload_file_to_minio(obw_img, f"{session_id}/obw/{obw_img.filename}")

    path_har_fmspa = upload_file_to_minio(harmonisa_fmspa, f"{session_id}/harmonisa/{harmonisa_fmspa.filename}")
    path_har_img = upload_file_to_minio(harmonisa_img, f"{session_id}/harmonisa/{harmonisa_img.filename}")

    path_dev_fmspa = upload_file_to_minio(deviasi_fmspa, f"{session_id}/deviasi/{deviasi_fmspa.filename}")
    path_dev_img = upload_file_to_minio(deviasi_img, f"{session_id}/deviasi/{deviasi_img.filename}")

    # catat rekor sesi di postgreSQL
    sesi_baru = MeasurementSession(
        session_uuid=session_id,
        stasiun_id=int(stasiun_id),
        obw_fmspa_path=path_obw_fmspa,
        obw_img_path=path_obw_img,
        harmonisa_fmspa_path=path_har_fmspa,
        harmonisa_img_path=path_har_img,
        deviasi_fmspa_path=path_dev_fmspa,
        deviasi_img_path=path_dev_img,
        status='uploaded'
    )

    db.session.add(sesi_baru)
    db.session.commit()

    # Memicu Job ke Redis Queue untuk diproses oleh Worker XML Parser
    REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    try:
        redis_conn = Redis.from_url(REDIS_URL)
        q = Queue('parse_xml_tasks', connection=redis_conn)
        q.enqueue('worker.process_xml_parsing_job', session_id)
        print(f"Job parsing {session_id} berhasil dikirim ke Redis Queue.")
    except Exception as e:
        print(f"Redis Enqueue Warning: {e}")

    # Langsung arahkan ke Halaman Detail Sesi Pengukuran
    return redirect(url_for('main.sesi_detail_view', session_uuid=session_id))

# 4. Halaman Detail Hasil Parsing Sesi Pengukuran
@main_bp.route('/sesi/detail/<session_uuid>', methods=['GET'])
def sesi_detail_view(session_uuid):
    sesi = MeasurementSession.query.filter_by(session_uuid=session_uuid).first_or_404()
    hasil = HasilPengukuran.query.filter_by(stasiun_id=sesi.stasiun_id).order_by(HasilPengukuran.id.desc()).first()
    return render_template('sesi_detail.html', sesi=sesi, hasil=hasil)


# 5. Rute untuk Menghapus Sesi Pengukuran (POST)
@main_bp.route('/sesi/hapus/<session_uuid>', methods=['POST'])
def hapus_sesi(session_uuid):
    sesi = MeasurementSession.query.filter_by(session_uuid=session_uuid).first_or_404()
    db.session.delete(sesi)
    db.session.commit()
    sesi_list = MeasurementSession.query.order_by(MeasurementSession.id.desc()).all()
    return render_template('sesi_list.html', sesi_list=sesi_list)

# 6. Rute Pemicu Analisis AI LLM (POST)
@main_bp.route('/sesi/analisis-ai/<session_uuid>', methods=['POST'])
def pemicu_analisis_ai(session_uuid):
    sesi = MeasurementSession.query.filter_by(session_uuid=session_uuid).first_or_404()

    # Memicu Job ke Redis Queue 'llm_tasks' untuk diproses oleh Worker AI Harness
    REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")

    # Verifikasi apakah ada AI Harness Worker yang aktif sebelum merubah status sesi
    try:
        from redis import Redis
        from rq import Worker
        redis_conn = Redis.from_url(REDIS_URL)
        workers = Worker.all(connection=redis_conn)
        ai_worker_active = any('llm_tasks' in [q.name for q in w.queues] for w in workers)
    except Exception as e:
        print(f"Gagal memverifikasi status AI Harness Worker: {e}")
        ai_worker_active = False

    if not ai_worker_active:
        flash("Gagal memicu Analisis AI: Layanan AI Harness Worker sedang offline (tidak aktif). Silakan jalankan worker.py di folder services/ai-harness terlebih dahulu sebelum menekan tombol ini!", "danger")
        hasil = HasilPengukuran.query.filter_by(stasiun_id=sesi.stasiun_id).order_by(HasilPengukuran.id.desc()).first()
        return render_template('sesi_detail.html', sesi=sesi, hasil=hasil)

    sesi.status = 'analyzing'
    db.session.commit()

    try:
        from redis import Redis
        from rq import Queue
        redis_conn = Redis.from_url(REDIS_URL)
        q = Queue('llm_tasks', connection=redis_conn)
        q.enqueue('worker.process_llm_analysis_job', session_uuid)
        print(f"Job LLM {session_uuid} berhasil dikirim ke Redis Queue 'llm_tasks'.")
    except Exception as e:
        print(f"Redis Enqueue LLM Warning: {e}")

    hasil = HasilPengukuran.query.filter_by(stasiun_id=sesi.stasiun_id).order_by(HasilPengukuran.id.desc()).first()
    return render_template('sesi_detail.html', sesi=sesi, hasil=hasil)



# RUTE EKSPOR LAPORAN MULTI-STASIUN (WORD & PDF)

@main_bp.route('/export/word', methods=['POST'])
def export_word():
    session_uuids = request.form.getlist('session_uuids')
    if not session_uuids:
        flash("Pilih minimal satu sesi pengukuran untuk diekspor!", "warning")
        return redirect(url_for('main.sesi_pengukuran_view'))
    sessions_data = []
    for suid in session_uuids:
        sesi = MeasurementSession.query.filter_by(session_uuid=suid).first()
        if sesi:
            stasiun = StasiunRadio.query.get(sesi.stasiun_id)
            hasil = HasilPengukuran.query.filter_by(stasiun_id=sesi.stasiun_id).order_by(HasilPengukuran.id.desc()).first()
            sessions_data.append((sesi, stasiun, hasil))
    doc_io = generate_word_report(sessions_data)
    return send_file(
        doc_io,
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        as_attachment=True,
        download_name='Laporan_Hasil_Pengukuran_Balmon_SFR.docx'
    )
@main_bp.route('/export/pdf', methods=['POST'])
def export_pdf():
    session_uuids = request.form.getlist('session_uuids')
    if not session_uuids:
        flash("Pilih minimal satu sesi pengukuran untuk diekspor!", "warning")
        return redirect(url_for('main.sesi_pengukuran_view'))
    sessions_data = []
    for suid in session_uuids:
        sesi = MeasurementSession.query.filter_by(session_uuid=suid).first()
        if sesi:
            stasiun = StasiunRadio.query.get(sesi.stasiun_id)
            hasil = HasilPengukuran.query.filter_by(stasiun_id=sesi.stasiun_id).order_by(HasilPengukuran.id.desc()).first()
            sessions_data.append((sesi, stasiun, hasil))
    pdf_io = generate_pdf_report(sessions_data)
    return send_file(
        pdf_io,
        mimetype='application/pdf',
        as_attachment=True,
        download_name='Laporan_Hasil_Pengukuran_Balmon_SFR.pdf'
    )


#endpoint telegram

@main_bp.route('/api/internal/telegram/kota', methods=['GET'])
def api_telegram_daftar_kota():
    """Mengambil daftar unik kota/kabupaten yang ada di database secara dinamis"""
    cities = db.session.query(StasiunRadio.kab_kota).distinct().order_by(StasiunRadio.kab_kota.asc()).all()
    city_list = [c[0] for c in cities if c[0]]
    return {"status": "success", "data": city_list}, 200


@main_bp.route('/api/internal/telegram/stasiun-by-kota', methods=['GET'])
def api_telegram_stasiun_by_kota():
    """Mengambil daftar stasiun radio berdasarkan nama kota terpilih"""
    kota = request.args.get('kota', '').strip()
    if not kota:
        return {"status": "error", "message": "Parameter 'kota' diperlukan"}, 400

    stasiun_list = StasiunRadio.query.filter_by(kab_kota=kota).order_by(StasiunRadio.nama_stasiun.asc()).all()
    data = [{
        "id": s.id,
        "nama_stasiun": s.nama_stasiun,
        "frekuensi_mhz": s.frekuensi_mhz,
        "penyelenggara": s.nama_penyelenggara,
        "kab_kota": s.kab_kota
    } for s in stasiun_list]
    return {"status": "success", "data": data}, 200


@main_bp.route('/api/internal/telegram/upload-sesi', methods=['POST'])
def api_telegram_upload_sesi():
    """Menerima 6 file upload dari Telegram Bot, simpan ke MinIO & picu Worker XML & AI"""
    stasiun_id = request.form.get('stasiun_id')
    if not stasiun_id:
        return {"status": "error", "message": "stasiun_id diperlukan"}, 400

    obw_fmspa = request.files.get('obw_fmspa')
    obw_img = request.files.get('obw_img')
    harmonisa_fmspa = request.files.get('harmonisa_fmspa')
    harmonisa_img = request.files.get('harmonisa_img')
    deviasi_fmspa = request.files.get('deviasi_fmspa')
    deviasi_img = request.files.get('deviasi_img')

    if not (obw_fmspa and obw_img and harmonisa_fmspa and harmonisa_img and deviasi_fmspa and deviasi_img):
        return {"status": "error", "message": "Semua 6 file (3 .fmspa + 3 gambar) WAJIB diunggah!"}, 400

    session_id = str(uuid.uuid4())

    # Unggah ke MinIO
    path_obw_fmspa = upload_file_to_minio(obw_fmspa, f"{session_id}/obw/{obw_fmspa.filename}")
    path_obw_img = upload_file_to_minio(obw_img, f"{session_id}/obw/{obw_img.filename}")
    path_harmonisa_fmspa = upload_file_to_minio(harmonisa_fmspa, f"{session_id}/harmonisa/{harmonisa_fmspa.filename}")
    path_harmonisa_img = upload_file_to_minio(harmonisa_img, f"{session_id}/harmonisa/{harmonisa_img.filename}")
    path_deviasi_fmspa = upload_file_to_minio(deviasi_fmspa, f"{session_id}/deviasi/{deviasi_fmspa.filename}")
    path_deviasi_img = upload_file_to_minio(deviasi_img, f"{session_id}/deviasi/{deviasi_img.filename}")

    # Simpan ke tabel measurement_session
    sesi_baru = MeasurementSession(
        session_uuid=session_id,
        stasiun_id=int(stasiun_id),
        status='uploaded',
        obw_fmspa_path=path_obw_fmspa,
        obw_img_path=path_obw_img,
        harmonisa_fmspa_path=path_harmonisa_fmspa,
        harmonisa_img_path=path_harmonisa_img,
        deviasi_fmspa_path=path_deviasi_fmspa,
        deviasi_img_path=path_deviasi_img
    )
    db.session.add(sesi_baru)
    db.session.commit()

    # Masukkan ke antrean Redis Queue (parse_xml_tasks)
    REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    try:
        from redis import Redis
        from rq import Queue
        redis_conn = Redis.from_url(REDIS_URL)
        q = Queue('parse_xml_tasks', connection=redis_conn)
        q.enqueue('worker.process_xml_parsing_job', session_id)
        print(f"[Telegram API] Sesi {session_id} berhasil masuk antrean XML Parser.")
    except Exception as e:
        print(f"Redis Enqueue Warning: {e}")

    return {
        "status": "success",
        "session_uuid": session_id,
        "message": "Sesi pengukuran berhasil disimpan dan masuk antrean proses."
    }, 201


@main_bp.route('/api/internal/telegram/sesi-paginated', methods=['GET'])
def api_telegram_sesi_paginated():
    """Mengambil daftar riwayat sesi terpaginasi (15 per halaman)"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 15, type=int)

    pagination = MeasurementSession.query.order_by(MeasurementSession.id.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    data = []
    for sesi in pagination.items:
        stasiun = StasiunRadio.query.get(sesi.stasiun_id)
        hasil = HasilPengukuran.query.filter_by(stasiun_id=sesi.stasiun_id)\
            .filter(HasilPengukuran.catatan_llm != None)\
            .order_by(HasilPengukuran.id.desc()).first() or \
            HasilPengukuran.query.filter_by(stasiun_id=sesi.stasiun_id).order_by(HasilPengukuran.id.desc()).first()
        data.append({
            "session_uuid": sesi.session_uuid,
            "nama_stasiun": stasiun.nama_stasiun if stasiun else "Tidak Diketahui",
            "frekuensi_mhz": stasiun.frekuensi_mhz if stasiun else "-",
            "kab_kota": stasiun.kab_kota if stasiun else "-",
            "status": sesi.status,
            "tanggal": sesi.created_at.strftime('%d-%m-%Y %H:%M') if sesi.created_at else "-",
            "ada_catatan_llm": bool(hasil and hasil.catatan_llm)
        })

    return {
        "status": "success",
        "page": pagination.page,
        "total_pages": pagination.pages,
        "total_items": pagination.total,
        "has_next": pagination.has_next,
        "has_prev": pagination.has_prev,
        "data": data
    }, 200


@main_bp.route('/api/internal/telegram/export/word/<session_uuid>', methods=['GET'])
def api_telegram_export_word(session_uuid):
    """Menghasilkan file Word (.docx) langsung untuk dikirim ke Telegram"""
    sesi = MeasurementSession.query.filter_by(session_uuid=session_uuid).first_or_404()
    stasiun = StasiunRadio.query.get(sesi.stasiun_id)
    hasil = HasilPengukuran.query.filter_by(stasiun_id=sesi.stasiun_id)\
        .filter(HasilPengukuran.catatan_llm != None)\
        .order_by(HasilPengukuran.id.desc()).first() or \
        HasilPengukuran.query.filter_by(stasiun_id=sesi.stasiun_id).order_by(HasilPengukuran.id.desc()).first()

    doc_io = generate_word_report([(sesi, stasiun, hasil)])
    return send_file(
        doc_io,
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        as_attachment=True,
        download_name=f'Laporan_{stasiun.nama_stasiun}_{sesi.session_uuid[:8]}.docx'
    )


@main_bp.route('/api/internal/telegram/export/pdf/<session_uuid>', methods=['GET'])
def api_telegram_export_pdf(session_uuid):
    """Menghasilkan file PDF (.pdf) langsung untuk dikirim ke Telegram"""
    sesi = MeasurementSession.query.filter_by(session_uuid=session_uuid).first_or_404()
    stasiun = StasiunRadio.query.get(sesi.stasiun_id)
    hasil = HasilPengukuran.query.filter_by(stasiun_id=sesi.stasiun_id)\
        .filter(HasilPengukuran.catatan_llm != None)\
        .order_by(HasilPengukuran.id.desc()).first() or \
        HasilPengukuran.query.filter_by(stasiun_id=sesi.stasiun_id).order_by(HasilPengukuran.id.desc()).first()

    pdf_io = generate_pdf_report([(sesi, stasiun, hasil)])
    return send_file(
        pdf_io,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'Laporan_{stasiun.nama_stasiun}_{sesi.session_uuid[:8]}.pdf'
    )

@main_bp.route('/api/internal/telegram/laporan/<session_uuid>', methods=['GET'])
def api_telegram_detail_laporan(session_uuid):
    """Mengambil detail laporan audit AI sesi tertentu untuk dikirim ke chat Telegram"""
    sesi = MeasurementSession.query.filter_by(session_uuid=session_uuid).first()
    if not sesi:
        return {"status": "error", "message": "Sesi tidak ditemukan"}, 404

    stasiun = StasiunRadio.query.get(sesi.stasiun_id)
    hasil = HasilPengukuran.query.filter_by(stasiun_id=sesi.stasiun_id)\
        .filter(HasilPengukuran.catatan_llm != None)\
        .order_by(HasilPengukuran.id.desc()).first() or \
        HasilPengukuran.query.filter_by(stasiun_id=sesi.stasiun_id).order_by(HasilPengukuran.id.desc()).first()

    return {
        "status": "success",
        "session_uuid": sesi.session_uuid,
        "stasiun": {
            "nama_stasiun": stasiun.nama_stasiun if stasiun else "-",
            "penyelenggara": stasiun.nama_penyelenggara if stasiun else "-",
            "frekuensi_mhz": stasiun.frekuensi_mhz if stasiun else "-",
            "kab_kota": stasiun.kab_kota if stasiun else "-"
        },
        "pengukuran": {
            "obw_khz": hasil.band_width_khz if hasil else "-",
            "deviasi_khz": hasil.deviasi_khz if hasil else "-",
            "level_dbm": hasil.level_dbm if hasil else "-"
        } if hasil else None,
        "catatan_llm": hasil.catatan_llm if hasil and hasil.catatan_llm else "Laporan Audit AI belum dijalankan atau masih dalam proses."
    }, 200
