from app import db
from datetime import datetime
import uuid

class MeasurementSession(db.Model):
    __tablename__ = 'measurement_session'

    id = db.Column(db.Integer, primary_key=True)
    session_uuid = db.Column(db.String(36), default=lambda: str(uuid.uuid4()), unique=True, nullable=False)

    # nyambung ke tabel master stasiun_radio
    stasiun_id = db.Column(db.Integer, db.ForeignKey('stasiun_radio.id'), nullable=False)
    stasiun = db.relationship('StasiunRadio', backref=db.backref('sessions', lazy=True))

    tanggal_sesi =db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(50), default='uploaded') # uploaded, parsing, analyzing, completed

    # lokasi 6 file di MinIO (3 pasang .fmspa sama gambar .png)
    obw_fmspa_path = db.Column(db.String(255), nullable=False)
    obw_img_path = db.Column(db.String(255), nullable=False)

    harmonisa_fmspa_path = db.Column(db.String(255), nullable=False)
    harmonisa_img_path = db.Column(db.String(255), nullable=False)

    deviasi_fmspa_path = db.Column(db.String(255), nullable=False)
    deviasi_img_path = db.Column(db.String(255), nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<MeasurementSession {self.session_uuid} - Stasiun {self.stasiun_id}>"
