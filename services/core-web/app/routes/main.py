import os
import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file
from app import db
from app.models.radio import StasiunRadio
from app.models.session import MeasurementSession
from app.minio_client import upload_file_to_minio
from app.export_helper import generate_word_report, generate_pdf_report


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
    return render_template('dashboard.html')

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
    hasil = HasilPengukuran.query.filter_by(stasiun_id=sesi.stasiun_id)\
        .filter(HasilPengukuran.catatan_llm != None)\
        .order_by(HasilPengukuran.id.desc()).first() or \
        HasilPengukuran.query.filter_by(stasiun_id=sesi.stasiun_id).order_by(HasilPengukuran.id.desc()).first()
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


# endpoint internal API untuk telegram bot (satu jalur saja walau microservices)

@main_bp.route('/api/internal/telegram/stasiun', methods=['GET'])
def api_telegram_cari_stasiun():
    """Mencari data master stasiun radio berdasarkan nama atau frekuensi"""
    query = request.args.get('q', '').strip()
    if not query:
        return {"status": "error", "message": "Parameter pencarian 'q' diperlukan"}, 400

    # Cari berdasarkan kecocokan nama stasiun, kota, atau frekuensi
    try:
        freq_float = float(query)
        stasiun_list = StasiunRadio.query.filter(
            (StasiunRadio.frekuensi_mhz == freq_float) |
            (StasiunRadio.nama_stasiun.ilike(f"%{query}%")) |
            (StasiunRadio.kab_kota.ilike(f"%{query}%"))
        ).limit(5).all()
    except ValueError:
        stasiun_list = StasiunRadio.query.filter(
            (StasiunRadio.nama_stasiun.ilike(f"%{query}%")) |
            (StasiunRadio.kab_kota.ilike(f"%{query}%"))
        ).limit(5).all()
    data = []
    for s in stasiun_list:
        hasil = HasilPengukuran.query.filter_by(stasiun_id=s.id).order_by(HasilPengukuran.id.desc()).first()
        data.append({
            "id": s.id,
            "nama_stasiun": s.nama_stasiun,
            "penyelenggara": s.nama_penyelenggara,
            "kab_kota": s.kab_kota,
            "frekuensi_mhz": s.frekuensi_mhz,
            "kanal": s.kanal or "-",
            "sub_servis": s.sub_servis or "-",
            "hasil_terakhir": {
                "tanggal": hasil.tanggal_pengukuran.strftime('%d-%m-%Y') if hasil and hasil.tanggal_pengukuran else "-",
                "obw_khz": hasil.band_width_khz if hasil else None,
                "deviasi_khz": hasil.deviasi_khz if hasil else None,
                "level_dbm": hasil.level_dbm if hasil else None
            } if hasil else None
        })
    return {"status": "success", "total": len(data), "data": data}, 200
@main_bp.route('/api/internal/telegram/sesi-terbaru', methods=['GET'])
def api_telegram_sesi_terbaru():
    """Mengambil riwayat 5 sesi pengukuran terbaru untuk Telegram"""
    sesi_list = MeasurementSession.query.order_by(MeasurementSession.id.desc()).limit(5).all()
    data = []
    for sesi in sesi_list:
        stasiun = StasiunRadio.query.get(sesi.stasiun_id)
        hasil = HasilPengukuran.query.filter_by(stasiun_id=sesi.stasiun_id).order_by(HasilPengukuran.id.desc()).first()
        data.append({
            "session_uuid": sesi.session_uuid,
            "nama_stasiun": stasiun.nama_stasiun if stasiun else "Tidak Diketahui",
            "frekuensi_mhz": stasiun.frekuensi_mhz if stasiun else "-",
            "kab_kota": stasiun.kab_kota if stasiun else "-",
            "status": sesi.status,
            "tanggal": sesi.created_at.strftime('%d-%m-%Y %H:%M') if sesi.created_at else "-",
            "ada_catatan_llm": bool(hasil and hasil.catatan_llm)
        })
    return {"status": "success", "data": data}, 200
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
