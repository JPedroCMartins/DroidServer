# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""E8 — Vazão de um microsserviço no Worker (QP3), comparada ao Termux nativo.

Alvos:
  worker  a API de demonstração rodando no Worker (padrão demo_api:8080)
  nativo  o MESMO app.py, copiado do Worker e executado no Termux, fora do
          PRoot (porta 8090), só durante o experimento
Para cada alvo e concorrência, o `hey` (no PC) faz requisições por
`--duracao` segundos. Durante a carga, o painel é consultado a cada 2 s para
registrar a CPU do DroidServer e a do Worker.

Requer o `hey` instalado no PC (https://github.com/rakyll/hey).

Uso:
  DROID_SSH="-p 8022 192.168.1.5" uv run bench/e8_vazao.py --worker demo_api --porta 8080 \\
      --concorrencias 1 10 50 --repeticoes 5 --duracao 20
"""

import argparse
import re
import shutil
import subprocess
import threading
import time

import requests

import comum

PORTA_NATIVA = 8090


def iniciar_nativo(worker):
    """Roda o mesmo app.py fora do PRoot.

    O app lê /etc/os-release (platform.freedesktop_os_release), que não existe
    no Termux: aponta o Python para o os-release do próprio container, sem
    alterar o app. O Python guarda o resultado em cache, então o trabalho por
    requisição é o mesmo nos dois alvos.
    """
    raiz = f"$PREFIX/var/lib/proot-distro/containers/{worker}/rootfs"
    lancador = ("import platform, runpy, sys; "
                "platform._os_release_candidates = (sys.argv[1] + '/etc/os-release',); "
                "runpy.run_path('droid_e8_app.py', run_name='__main__')")
    comum.ssh(f"cp {raiz}/app/app.py $PREFIX/tmp/droid_e8_app.py && cd $PREFIX/tmp && "
              f"(PORT={PORTA_NATIVA} WORKER=nativo nohup python3 -c \"{lancador}\" {raiz} "
              f"> droid_e8.log 2>&1 &)")


def parar_nativo():
    comum.ssh("pkill -f 'droid_e8_app.py'; rm -f $PREFIX/tmp/droid_e8_app.py $PREFIX/tmp/droid_e8.log")


def hey(url, concorrencia, duracao):
    saida = subprocess.run(["hey", "-z", f"{duracao}s", "-c", str(concorrencia), url],
                           capture_output=True, text=True, timeout=duracao + 60).stdout

    def num(padrao):
        m = re.search(padrao, saida)
        return float(m.group(1)) if m else None

    total = sum(int(n) for n in re.findall(r"\[\d{3}\]\s+(\d+) responses", saida))
    ok = sum(int(n) for c, n in re.findall(r"\[(\d{3})\]\s+(\d+) responses", saida) if c.startswith("2"))
    # bloco "Error distribution:" com linhas "  [N]\tGet ...: <erro>"
    bloco_erros = saida.split("Error distribution:", 1)[1] if "Error distribution:" in saida else ""
    erros = sum(int(n) for n in re.findall(r"^\s*\[(\d+)\]", bloco_erros, re.M))
    # Vazão útil: só respostas 2xx (o "Requests/sec" do hey conta também os erros)
    return {
        "req_s": round(ok / duracao, 2),
        "req_s_hey": num(r"Requests/sec:\s+([\d.]+)"),
        "p50_ms": (num(r"50%+ in ([\d.]+) secs") or 0) * 1000,
        "p95_ms": (num(r"95%+ in ([\d.]+) secs") or 0) * 1000,
        "p99_ms": (num(r"99%+ in ([\d.]+) secs") or 0) * 1000,
        "respostas": total, "respostas_2xx": ok, "erros": erros,
    }


class AmostradorCPU(threading.Thread):
    """Lê a CPU do DroidServer e do Worker no painel enquanto a carga roda."""

    def __init__(self, s, ip, worker):
        super().__init__(daemon=True)
        self.s, self.ip, self.worker = s, ip, worker
        self.parar = threading.Event()
        self.droidserver, self.do_worker = [], []

    def run(self):
        visto = None
        while not self.parar.wait(2):
            try:
                n = comum.estado_node(self.s, self.ip)
            except Exception:
                continue
            if n.get("last_seen") == visto:  # só amostras novas (o sync é a cada 10 s)
                continue
            visto = n.get("last_seen")
            if n.get("cpu_termux") is not None:
                self.droidserver.append(n["cpu_termux"])
            cw = (n.get("cpu_workers") or {}).get(self.worker)
            if cw is not None:
                self.do_worker.append(cw)


def media(v):
    return round(sum(v) / len(v), 2) if v else ""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--worker", default="demo_api")
    ap.add_argument("--porta", type=int, default=8080)
    ap.add_argument("--concorrencias", type=int, nargs="+", default=[1, 10, 50])
    ap.add_argument("--repeticoes", type=int, default=5)
    ap.add_argument("--duracao", type=int, default=20)
    ap.add_argument("--sem-nativo", action="store_true", help="mede só o Worker")
    args = ap.parse_args()
    if not shutil.which("hey"):
        raise SystemExit("Instale o `hey` no PC.")

    s = comum.sessao_painel()
    ip = comum.ip_do_node(s)
    alvos = {"worker": f"http://{ip}:{args.porta}/"}
    if not args.sem_nativo:
        iniciar_nativo(args.worker)
        alvos["nativo"] = f"http://{ip}:{PORTA_NATIVA}/"
        for _ in range(20):
            try:
                if requests.get(alvos["nativo"], timeout=2).ok:
                    break
            except requests.RequestException:
                pass
            time.sleep(1)
        else:
            parar_nativo()
            raise SystemExit("O servidor nativo não respondeu 2xx: confira o log no aparelho.")

    csv = comum.GravadorCSV(comum.arquivo_csv("e8_vazao"), [
        "alvo", "concorrencia", "repeticao", "duracao_s", "req_s", "req_s_hey", "p50_ms", "p95_ms", "p99_ms",
        "respostas", "respostas_2xx", "erros", "cpu_droidserver_media", "cpu_worker_media", "carimbo"])
    resultados = {}
    try:
        for rep in range(1, args.repeticoes + 1):
            for conc in args.concorrencias:
                for alvo, url in (alvos.items() if rep % 2 else reversed(list(alvos.items()))):
                    cpu = AmostradorCPU(s, ip, args.worker)
                    cpu.start()
                    r = hey(url, conc, args.duracao)
                    cpu.parar.set()
                    cpu.join()
                    csv.linha(alvo=alvo, concorrencia=conc, repeticao=rep, duracao_s=args.duracao, **r,
                              cpu_droidserver_media=media(cpu.droidserver), cpu_worker_media=media(cpu.do_worker),
                              carimbo=comum.carimbo())
                    resultados.setdefault((alvo, conc), []).append(r["req_s"])
                    print(f"[{rep}/{args.repeticoes}] {alvo:6} c={conc:<3} {r['req_s']} req/s, "
                          f"p95 {r['p95_ms']:.0f} ms, 2xx {r['respostas_2xx']}/{r['respostas']}, "
                          f"CPU DroidServer {media(cpu.droidserver)}%, Worker {media(cpu.do_worker)}%", flush=True)
                    time.sleep(3)
    finally:
        if not args.sem_nativo:
            parar_nativo()
        csv.fechar()

    print(f"\nDados: {csv.caminho}")
    for (alvo, conc), valores in sorted(resultados.items()):
        comum.imprimir_resumo(f"{alvo:6} c={conc:<3}", [v for v in valores if v], "req/s")


if __name__ == "__main__":
    main()
