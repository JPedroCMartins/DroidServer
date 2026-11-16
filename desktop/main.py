from app import create_app, opcoes_servidor, socketio

app = create_app()

if __name__ == '__main__':
    socketio.run(app, **opcoes_servidor())
