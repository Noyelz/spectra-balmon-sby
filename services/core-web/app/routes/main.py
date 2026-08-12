import os
import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from app import db
from app.models.radio import StasiunRadio
from app.models.session import MeasurementSession
from app.minio_client import upload_file_to_minio

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

# rute halaman upload: sesi pengkuran (upload 6 file per stasiun)

# 1. menampilkan form sesi pengukuran baru
@main_bp.route('/sesi-pengukuran', methods=['GET'])
def sesi_pengukuran_view():
    stasiun_list = StasiunRadio.query.order_by(StasiunRadio.nama_stasiun.asc()).all()
    selected_id = request.args.get('stasiun_id', type=int)
    selected_stasiun = StasiunRadio.query.get(selected_id) if selected_id else None
    
    return render_template(
        'sesi_pengukuran.html',
        stasiun_list=stasiun_list,
        selected_stasiun=selected_stasiun
    )

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

    return f"""
    <div style="background: #e6ffed; border: 1px solid #2da44e; color: #1a7f37; padding: 15px; border-radius: 2px; margin-top: 15px;">
    <h4 style="margin-top:0;">Sesi Pengukuran Berhasil Dibuat!</h4>
    <p>UUID Sesi: <strong>{session_id}</strong></p>
    <p>Seluruh 6 file telah sukses disimpan di Object Storage (MinIO). Status: <strong>Uploaded (Menunggu Queue Parser)</strong>.</p>
    <div>
    """
    