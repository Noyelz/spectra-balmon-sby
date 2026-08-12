from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from app.config import Config, ensure_database_exists

# membuat alat koneksi database yang masih kosong
db = SQLAlchemy()
migrate = Migrate()

def create_app():
    #membuat aplikasi flask
    flask_app = Flask(__name__)

    flask_app.config.from_object(Config)

    ensure_database_exists()

    db.init_app(flask_app)
    migrate.init_app(flask_app, db)

    import app.models.radio
    import app.models.user
    import app.models.session

    with flask_app.app_context():
        db.create_all()
        print("Semua database terverifikasi dan siap digunakan")

    from app.routes.main import main_bp
    flask_app.register_blueprint(main_bp)

    return flask_app