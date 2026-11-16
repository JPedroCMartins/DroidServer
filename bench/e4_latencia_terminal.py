# /// script
# requires-python = ">=3.10"
# dependencies = ["requests", "python-socketio[client]>=5"]
# ///
"""E4 — Latência de eco do terminal (QP2).

Mede o tempo entre enviar uma tecla pelo WebSocket do painel e o eco dela
voltar do shell do Worker: navegador -> Host -> Node -> PTY -> Node -> Host.
Cada amostra é uma tecla ("a") seguida de um backspace (os dois são medidos),
para a linha do shell não crescer.

Uso:
  uv run bench/e4_latencia_terminal.py --worker demo_api --amostras 500
"""

import argparse
import threading
import time

import socketio

import comum


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--worker", default="demo_api")
    ap.add_argument("--amostras", type=int, default=500, help="teclas (cada uma gera 2 medições)")
    ap.add_argument("--intervalo", type=float, default=0.05, help="pausa entre medições (s)")
    ap.add_argument("--timeout", type=float, default=3.0)
    args = ap.parse_args()

    s = comum.sessao_painel()
    ip = comum.ip_do_node(s)
    alias = args.worker

    chegou = threading.Event()
    instante = {"t": None}

    sio = socketio.Client(reconnection=False)

    @sio.on(f"output_for_{ip}_{alias}")
    def _saida(_dados):
        if instante["t"] is None:
            instante["t"] = time.perf_counter()
        chegou.set()

    cookie = "; ".join(f"{c.name}={c.value}" for c in s.cookies)
    sio.connect(comum.HOST_URL, headers={"Cookie": cookie} if cookie else {}, transports=["websocket"])
    sio.emit("terminal_assinar", {"ip": ip, "alias": alias})
    sio.emit("terminal_resize", {"ip": ip, "alias": alias, "cols": 120, "rows": 30})
    print(f"Node {ip}, worker {alias}: abrindo o terminal...")
    time.sleep(5)  # sessão do proot-distro + prompt

    def medir(tecla):
        time.sleep(args.intervalo)
        chegou.clear()
        instante["t"] = None
        t0 = time.perf_counter()
        sio.emit("terminal_input", {"ip": ip, "alias": alias, "input": tecla})
        if not chegou.wait(args.timeout):
            return None
        return (instante["t"] - t0) * 1000

    for _ in range(10):  # aquecimento
        medir("a")
        medir("\x7f")

    csv = comum.GravadorCSV(comum.arquivo_csv("e4_latencia_terminal"),
                            ["amostra", "tecla", "latencia_ms", "carimbo"])
    latencias, perdidas = [], 0
    for i in range(args.amostras):
        for tecla, nome in (("a", "letra"), ("\x7f", "backspace")):
            ms = medir(tecla)
            csv.linha(amostra=i, tecla=nome, latencia_ms="" if ms is None else round(ms, 3),
                      carimbo=comum.carimbo())
            if ms is None:
                perdidas += 1
            else:
                latencias.append(ms)
        if (i + 1) % 100 == 0:
            print(f"  {i + 1}/{args.amostras}")

    sio.emit("terminal_input", {"ip": ip, "alias": alias, "input": "exit\r"})
    sio.emit("terminal_cancelar", {"ip": ip, "alias": alias})
    time.sleep(0.5)
    sio.disconnect()
    csv.fechar()

    print(f"\nDados: {csv.caminho}")
    comum.imprimir_resumo("Latência de eco", latencias, "ms")
    print(f"Sem eco em {args.timeout:.0f} s: {perdidas}")


if __name__ == "__main__":
    main()
