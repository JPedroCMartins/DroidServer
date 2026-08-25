import logging
import os
from logging.handlers import RotatingFileHandler

from flask import Flask
from flask_socketio import SocketIO

# Inicializamos o SocketIO globalmente
socketio = SocketIO(cors_allowed_origins="*")


def _configurar_logging(app):
    """Registra em arquivo (rotativo) os logs do Flask, Werkzeug e SocketIO.

    Diretório configurável via DROID_LOG_DIR (padrão: desktop/logs/).
    """
    log_dir = os.getenv("DROID_LOG_DIR") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs"
    )
    os.makedirs(log_dir, exist_ok=True)

    # Evita duplicar handlers em chamadas repetidas de create_app (ex.: testes)
    if any(isinstance(h, RotatingFileHandler) for h in app.logger.handlers):
        return

    arquivo = os.path.join(log_dir, "droidserver.log")
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    fh = RotatingFileHandler(arquivo, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8")
    fh.setFormatter(formatter)
    fh.setLevel(logging.INFO)

    for nome in ("werkzeug", "flask_socketio", "socketio", "engineio"):
        lg = logging.getLogger(nome)
        lg.setLevel(logging.INFO)
        lg.addHandler(fh)

    app.logger.addHandler(fh)
    app.logger.setLevel(logging.INFO)
    app.logger.info("Aplicação iniciada. Log: %s", arquivo)


def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'chave_secreta_tcc'

    # Anexa o app ao SocketIO
    socketio.init_app(app)

    with app.app_context():
        from app import routes

    _configurar_logging(app)

    return app
