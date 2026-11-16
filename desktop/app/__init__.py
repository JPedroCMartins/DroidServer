import logging
import os
import secrets
from logging.handlers import RotatingFileHandler

from flask import Flask
from flask_socketio import SocketIO

# Inicializamos o SocketIO globalmente
# ping_timeout maior reduz desconexões com o long-polling do engineio no Termux
socketio = SocketIO(cors_allowed_origins="*", ping_interval=25, ping_timeout=60)


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
    # Chave de sessão: DROID_SECRET_KEY, ou uma aleatória a cada execução
    # (o painel não usa sessões persistentes, então não há o que perder).
    app.config['SECRET_KEY'] = os.getenv("DROID_SECRET_KEY") or secrets.token_hex(32)

    # Anexa o app ao SocketIO
    socketio.init_app(app)

    with app.app_context():
        from app import routes

    _configurar_logging(app)

    return app


def _env_bool(nome, padrao=False):
    valor = os.getenv(nome)
    if valor is None:
        return padrao
    return valor.strip().lower() in ("1", "true", "sim", "yes", "on")


def opcoes_servidor():
    """Parâmetros de socketio.run() lidos das variáveis de ambiente.

    DROID_BIND  -> endereço de escuta (padrão 0.0.0.0: os nodes precisam alcançar o host)
    DROID_PORT  -> porta (padrão 5050)
    DROID_DEBUG -> 1 liga o modo debug (padrão desligado)

    O modo debug do Werkzeug expõe um console Python interativo a quem
    alcançar a porta; por isso só é permitido escutando em localhost.

    allow_unsafe_werkzeug=True permite iniciar o servidor sem um terminal
    interativo (systemd, nohup, preview). Sem ele, o Flask-SocketIO recusa o
    Werkzeug quando não há TTY. Para um protótipo em LAN o Werkzeug basta;
    em produção use um servidor como gunicorn + eventlet/gevent.
    """
    host = os.getenv("DROID_BIND", "0.0.0.0")
    porta = int(os.getenv("DROID_PORT", "5050"))
    debug = _env_bool("DROID_DEBUG")
    if debug and host not in ("127.0.0.1", "localhost", "::1"):
        logging.getLogger("droidserver").warning(
            "DROID_DEBUG ignorado: o debugger do Werkzeug não pode ficar exposto em %s. "
            "Use DROID_BIND=127.0.0.1 para depurar localmente.", host)
        debug = False
    return {
        "host": host,
        "port": porta,
        "debug": debug,
        "use_reloader": debug,
        "allow_unsafe_werkzeug": True,
    }
