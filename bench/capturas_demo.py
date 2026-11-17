# /// script
# requires-python = ">=3.10"
# dependencies = ["requests", "python-socketio[client]>=5", "websocket-client", "playwright"]
# ///
"""Prints do painel para a apresentação, com um Node de DEMONSTRAÇÃO.

Não usa nenhum celular: sobe o Host deste repositório em 127.0.0.1 (pasta de
dados temporária, sem senha) e um Node fictício que fala com ele pelo mesmo
protocolo do agente real (POST /api/node_sync a cada 2 s + WebSocket com
papel "node"). O terminal responde a alguns comandos com saídas fixas.

Salva em desktop/app/static/apresentacao/:
  painel_dashboard.png   Dashboard com o Node e o gráfico de CPU/RAM aberto
  painel_node.png        Página do Node (criação de Worker e cartões)
  painel_terminal.png    Terminal de um Worker no navegador

Uso:
  uv run bench/capturas_demo.py            # tira os prints e encerra
  uv run bench/capturas_demo.py --servir   # só deixa o painel de demo no ar
                                           # (http://127.0.0.1:5099) até Ctrl+C
  DROID_DEMO_PORT=5100 uv run bench/capturas_demo.py --servir   # outra porta
"""

import argparse
import json
import math
import os
import random
import socket
import subprocess
import sys
import tempfile
import threading
import time

import requests
import socketio

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASTA = os.path.join(RAIZ, "desktop", "app", "static", "apresentacao")
PORTA = int(os.getenv("DROID_DEMO_PORT", "5099"))
HOST_URL = f"http://127.0.0.1:{PORTA}"
IP = "192.168.1.100"
TOKEN = "token-de-demonstracao"
WORKERS = ["demo_api", "banco_dados", "site_pessoal"]

PROMPT = "\x1b[1;32mroot@demo_api\x1b[0m:\x1b[1;34m~\x1b[0m# "
RESPOSTAS = {
    "cat /etc/os-release": (
        'NAME="Alpine Linux"\r\nID=alpine\r\nVERSION_ID=3.20.3\r\n'
        'PRETTY_NAME="Alpine Linux v3.20"\r\nHOME_URL="https://alpinelinux.org/"\r\n'),
    "uname -m": "aarch64\r\n",
    "free -m": ("              total        used        free      shared  buff/cache   available\r\n"
                "Mem:           3427        2311         402          21         713         998\r\n"),
    "curl -s localhost:8080/saude": '{"status": "ok", "servico": "demo_api"}\r\n',
}


def servicos():
    base = {"detalhe": "", "tem_script": True, "gerenciado": True, "autostart": True, "autorestart": True,
            "falhas_hoje": 0, "ultima_falha": None, "script_salvo_em": None}
    return {
        "demo_api": {**base, "estado": "RUNNING", "pid": 18342, "uptime": "6:12:40", "porta": 8080,
                     "distro": "alpine", "disco_mb": 14.2, "ram_mb": 31.5},
        "banco_dados": {**base, "estado": "RUNNING", "pid": 18377, "uptime": "6:12:38", "porta": 5432,
                        "distro": "debian", "disco_mb": 212.7, "ram_mb": 48.1},
        "site_pessoal": {**base, "estado": "STOPPED", "pid": None, "uptime": None, "porta": 8000,
                         "distro": "alpine", "disco_mb": 9.8, "ram_mb": None},
    }


def amostra(t):
    """CPU/RAM com variação suave, para o gráfico não ficar reto."""
    cpu = 6 + 3 * math.sin(t / 40) + random.uniform(-1, 1)
    ram = 66 + 2 * math.sin(t / 90) + random.uniform(-.4, .4)
    return round(max(cpu, 0.5), 1), round(ram, 1)


class NodeDemo:
    def __init__(self):
        self.sio = socketio.Client()
        self.linhas = {}
        for alias in WORKERS:
            self.sio.on(f"cmd_to_{IP}_{alias}", self._entrada(alias))
            # O navegador manda o tamanho ao abrir o terminal: como no agente, a sessão "abre" aí
            self.sio.on(f"resize_to_{IP}_{alias}",
                        lambda _d, a=alias: self._enviar(a, "\r\n" + PROMPT.replace("demo_api", a)))

    def _entrada(self, alias):
        def tratar(data):
            texto = (data or {}).get("input", "")
            buf = self.linhas.setdefault(alias, "")
            for ch in texto:
                if ch in "\r\n":
                    cmd = buf.strip()
                    buf = ""
                    saida = "\r\n"
                    if cmd == "clear":
                        saida = "\x1b[H\x1b[2J"
                    elif cmd:
                        saida += RESPOSTAS.get(cmd, f"sh: {cmd.split()[0]}: (demonstração)\r\n")
                    self._enviar(alias, saida + PROMPT.replace("demo_api", alias))
                elif ch == "\x7f":
                    if buf:
                        buf = buf[:-1]
                        self._enviar(alias, "\b \b")
                else:
                    buf += ch
                    self._enviar(alias, ch)
            self.linhas[alias] = buf
        return tratar

    def _enviar(self, alias, texto):
        self.sio.emit("terminal_output", {"alias": alias, "output": texto})

    def sync(self, historico=False):
        cpu, ram = amostra(time.time())
        total = 3427 * 1024 * 1024
        payload = {
            "ip": IP, "token": TOKEN, "status": "Online", "workers": WORKERS,
            "servicos": servicos(),
            "worker_status": {a: s["estado"] for a, s in servicos().items()},
            "tarefa_atual": None, "resultados": [], "logs_ativos": [],
            "cpu": round(cpu * 2.4, 1), "cpu_termux": cpu,
            "cpu_workers": {"demo_api": round(cpu * .5, 1), "banco_dados": round(cpu * .3, 1)},
            "mem": {"total": total, "usado": int(total * ram / 100), "percent": ram},
        }
        if historico:
            agora = time.time()
            payload["historico"] = [
                dict(zip(("cpu", "ram"), amostra(agora - s)), t=round(agora - s, 1))
                for s in range(600, 0, -10)]
        r = requests.post(f"{HOST_URL}/api/node_sync", json=payload, timeout=5)
        return r.json() if r.ok else {}

    def rodar(self, parar):
        pedir = True
        while not parar.is_set():
            try:
                resp = self.sync(historico=pedir)
                pedir = bool(resp.get("pedir_historico"))
                if not self.sio.connected:
                    self.sio.connect(HOST_URL, auth={"papel": "node", "ip": IP, "token": TOKEN},
                                     transports=["websocket"])
            except Exception as e:  # o host pode ainda estar subindo
                print("node demo:", e, file=sys.stderr)
            parar.wait(2)


def porta_ocupada():
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", PORTA)) == 0


def subir_host(pasta):
    # Outro painel na mesma porta responderia no lugar deste (ex.: uma demo
    # antiga ainda aberta), e as páginas mostrariam a versão velha.
    if porta_ocupada():
        raise SystemExit(f"A porta {PORTA} já está em uso (outra demonstração aberta?). "
                         f"Feche-a com Ctrl+C ou use outra porta: DROID_DEMO_PORT=5100 uv run bench/capturas_demo.py --servir")
    with open(os.path.join(pasta, "nodes.json"), "w") as f:
        json.dump({IP: {"token": TOKEN, "nome": "moto e40 (demo)"}}, f)
    env = {**os.environ, "DROID_DATA_DIR": pasta, "DROID_LOG_DIR": pasta, "DROID_BIND": "127.0.0.1",
           "DROID_PORT": str(PORTA), "DROID_PANEL_PASSWORD": ""}
    proc = subprocess.Popen(["uv", "run", "--project", os.path.join(RAIZ, "desktop"), "python", "main.py"],
                            cwd=os.path.join(RAIZ, "desktop"), env=env)
    for _ in range(60):
        if proc.poll() is not None:
            raise SystemExit("o Host de demonstração encerrou ao iniciar (veja o erro acima)")
        try:
            requests.get(HOST_URL + "/api/nodes", timeout=1)
            return proc
        except requests.RequestException:
            time.sleep(.5)
    proc.terminate()
    raise SystemExit("o Host de demonstração não subiu")


def capturar():
    from playwright.sync_api import sync_playwright

    def salvar(pagina, nome):
        caminho = os.path.join(PASTA, nome)
        pagina.screenshot(path=caminho)
        print("salvo:", os.path.relpath(caminho, RAIZ))

    def abrir(pagina, caminho, espera):
        pagina.goto(HOST_URL + caminho, wait_until="networkidle")
        time.sleep(espera)

    with sync_playwright() as p:
        navegador = p.chromium.launch(channel="chrome", headless=True)
        pagina = navegador.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1.5,
                                    color_scheme="dark", locale="pt-BR")
        abrir(pagina, "/", 3)
        pagina.locator(f'[data-grafico="{IP}"]').first.click()
        time.sleep(3)
        salvar(pagina, "painel_dashboard.png")

        abrir(pagina, f"/node/{IP}", 3)
        salvar(pagina, "painel_node.png")

        abrir(pagina, f"/node/{IP}/worker/demo_api/terminal", 3)
        pagina.locator(".xterm").first.click()
        for cmd in ("clear", "cat /etc/os-release", "uname -m", "free -m", "curl -s localhost:8080/saude"):
            pagina.keyboard.type(cmd + "\n", delay=15)
            time.sleep(.6)
        time.sleep(1)
        salvar(pagina, "painel_terminal.png")
        navegador.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--servir", action="store_true", help="só deixa o painel de demonstração no ar")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory(prefix="droid-demo-") as pasta:
        host = subir_host(pasta)
        parar = threading.Event()
        node = NodeDemo()
        threading.Thread(target=node.rodar, args=(parar,), daemon=True).start()
        try:
            time.sleep(3)
            if args.servir:
                print(f"Painel de demonstração em {HOST_URL} (Ctrl+C para sair)")
                while True:
                    time.sleep(3600)
            else:
                capturar()
        except KeyboardInterrupt:
            pass
        finally:
            parar.set()
            if node.sio.connected:
                node.sio.disconnect()
            host.terminate()
            host.wait(10)


if __name__ == "__main__":
    main()
