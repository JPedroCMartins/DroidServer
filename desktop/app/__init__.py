from flask import Flask
from flask_socketio import SocketIO

# Inicializamos o SocketIO globalmente
socketio = SocketIO(cors_allowed_origins="*")

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'chave_secreta_tcc'

    # Anexa o app ao SocketIO
    socketio.init_app(app)

    with app.app_context():
        from app import routes

    return app