from app import db
from datetime import datetime


# Tabel 1: data nama stasiun dll
class StasiunRadio(db.Model):
    __tablename__ = 'stasiun_radio'

    # ID Unik
    id = db.Column(db.Integer, primary_key=True)

    # info dasar
    nama_penyelenggara = db.Column(db.String(225), nullable=False)
    nama_stasiun = db.Column(db.String(225), nullable=False)
    kab_kota = db.Column(db.String(100), nullable=False)
    sub_servis = db.Column(db.String(100))
    kanal = db.Column(db.String(50))
    frekuensi_mhz = db.Column(db.Float, nullable=False)

    # relasi 1 stasiun radio bisa punya banyak hasil pengukuran
    pengukuran = db.relationship('HasilPengukuran', backref='stasiun', lazy=True)

    def __repr__(self):
        return f"<StasiunRadio {self.nama_stasiun} - {self.kab_kota}>"


# tabel 2 
class HasilPengukuran(db.Model):
    __tablename__ = 'hasil_pengukuran'

    id = db.Column(db.Integer, primary_key=True)

    # nyambung ke tabel stasiun radio di atas

    stasiun_id = db.Column(db.Integer, db.ForeignKey('stasiun_radio.id'), nullable=False)

    # tanggal pelaksanaan pengukurn lapangan
    tanggal_pengukuran = db.Column(db.Date, nullable=False)

    # parameter hasil ukur
    level_dbm = db.Column(db.Float)
    band_width_khz = db.Column(db.Float)
    deviasi_khz = db.Column(db.Float)
    h1_mhz = db.Column(db.Float)
    h1_db = db.Column(db.Float)
    h1_dbm = db.Column(db.Float)
    h2_mhz = db.Column(db.Float)
    h2_db = db.Column(db.Float)
    h2_dbm = db.Column(db.Float)
    h3_mhz = db.Column(db.Float)
    h3_db = db.Column(db.Float)
    h3_dbm = db.Column(db.Float)
    keterangan = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    