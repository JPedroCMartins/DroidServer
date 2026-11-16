# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""E7 — Disponibilidade de uma aplicação num Worker (QP3 / H1), com E6 e E10.

A cada `--intervalo` segundos:
  - faz GET na aplicação do Worker (http://<ip-do-node>:<porta>/) e registra
    se respondeu 2xx/3xx e em quanto tempo;
  - lê o estado do node no painel: Online/Offline, CPU do DroidServer, CPU do
    Worker, RAM do aparelho e o pid/uptime do serviço (pid novo = reinício).
A cada `--ssh-intervalo` segundos (se DROID_SSH estiver definido), mede a
memória (RSS) do agente e do supervisord no aparelho (E10).

Ao terminar (ou com --resumo arquivo.csv, a qualquer momento) calcula:
disponibilidade = respostas OK / total, reinícios do serviço, transições do
node para Offline (E6: falsos positivos com o aparelho ligado) e consumo.

Uso (deixar rodando de noite):
  DROID_SSH="-p 8022 192.168.1.5" nohup uv run bench/e7_disponibilidade.py \\
      --worker demo_api --porta 8080 --horas 24 > bench/resultados/e7.log 2>&1 &
  uv run bench/e7_disponibilidade.py --resumo bench/resultados/e7_disponibilidade_<data>.csv
"""

import argparse
import csv
import os
import time

import requests

import comum

CAMPOS = ["carimbo", "t", "http_ok", "http_status", "http_ms", "erro", "node_status", "cpu_droidserver",
          "cpu_worker", "ram_pct", "servico_estado", "servico_pid", "servico_uptime",
          "rss_agente_kb", "rss_supervisord_kb"]


def rss_no_aparelho():
    """RSS (kB) do agente (node.py) e do supervisord, via SSH."""
    # Padrões ancorados no início: sem isso o pgrep casaria com o próprio shell do SSH
    cmd = ("for p in '^python3 node.py' '^[^ ]*/python [^ ]*/supervisord'; do "
           "pid=$(pgrep -f \"$p\" | head -1); [ -n \"$pid\" ] && awk '/VmRSS/{print $2}' /proc/$pid/status || echo; done")
    try:
        _, saida = comum.ssh(cmd, timeout=30)
        linhas = (saida.splitlines() + ["", ""])[:2]
        return [int(x) if x.strip().isdigit() else "" for x in linhas]
    except Exception:
        return ["", ""]


def coletar(args):
    s = comum.sessao_painel()
    ip = comum.ip_do_node(s)
    url_app = f"http://{ip}:{args.porta}/"
    caminho = comum.arquivo_csv("e7_disponibilidade")
    gravador = comum.GravadorCSV(caminho, CAMPOS)
    print(f"E7: {url_app} (worker {args.worker}) por {args.horas} h, a cada {args.intervalo} s -> {caminho}",
          flush=True)

    fim = time.time() + args.horas * 3600
    proximo_ssh = 0
    usar_ssh = bool(os.getenv("DROID_SSH"))
    while time.time() < fim:
        inicio = time.time()
        linha = {"carimbo": comum.carimbo(), "t": round(inicio, 1)}

        try:
            t0 = time.perf_counter()
            r = requests.get(url_app, timeout=5)
            linha.update(http_ok=200 <= r.status_code < 400, http_status=r.status_code,
                         http_ms=round((time.perf_counter() - t0) * 1000, 1), erro="")
        except requests.RequestException as e:
            linha.update(http_ok=False, http_status="", http_ms="", erro=type(e).__name__)

        try:
            n = comum.estado_node(s, ip)
            sv = (n.get("servicos") or {}).get(args.worker) or {}
            linha.update(node_status=n.get("status"), cpu_droidserver=n.get("cpu_termux"),
                         cpu_worker=(n.get("cpu_workers") or {}).get(args.worker),
                         ram_pct=(n.get("mem") or {}).get("percent"), servico_estado=sv.get("estado"),
                         servico_pid=sv.get("pid"), servico_uptime=sv.get("uptime"))
        except Exception as e:
            linha.update(node_status=f"erro: {type(e).__name__}")
            try:  # sessão expirada ou Host reiniciado: loga de novo
                s = comum.sessao_painel()
            except SystemExit:
                pass

        if usar_ssh and inicio >= proximo_ssh:
            linha["rss_agente_kb"], linha["rss_supervisord_kb"] = rss_no_aparelho()
            proximo_ssh = inicio + args.ssh_intervalo

        gravador.linha(**{c: linha.get(c, "") for c in CAMPOS})
        time.sleep(max(0.0, args.intervalo - (time.time() - inicio)))

    gravador.fechar()
    resumir(caminho)


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def resumir(caminho):
    with open(caminho, encoding="utf-8") as f:
        linhas = list(csv.DictReader(f))
    if not linhas:
        print("Sem amostras.")
        return
    total = len(linhas)
    ok = sum(1 for l in linhas if l["http_ok"] == "True")
    horas = (float(linhas[-1]["t"]) - float(linhas[0]["t"])) / 3600

    # reinícios: troca de pid do serviço entre amostras consecutivas com pid conhecido
    pids = [l["servico_pid"] for l in linhas if l["servico_pid"]]
    reinicios = sum(1 for a, b in zip(pids, pids[1:]) if a != b)
    # E6: transições Online -> Offline vistas pelo painel
    estados = [l["node_status"] for l in linhas]
    quedas = sum(1 for a, b in zip(estados, estados[1:]) if a == "Online" and b != "Online")
    # maior sequência de falhas (indisponibilidade contínua)
    pior, atual = 0, 0
    for l in linhas:
        atual = atual + 1 if l["http_ok"] != "True" else 0
        pior = max(pior, atual)
    erros = {}
    for l in linhas:
        if l["http_ok"] != "True":
            erros[l["erro"] or l["http_status"]] = erros.get(l["erro"] or l["http_status"], 0) + 1

    intervalo = (horas * 3600 / (total - 1)) if total > 1 else 0
    print(f"\nE7 — {caminho}")
    print(f"Duração: {horas:.2f} h, {total} amostras (~{intervalo:.1f} s entre elas)")
    print(f"Disponibilidade: {100 * ok / total:.3f}% ({ok}/{total}); maior indisponibilidade contínua: "
          f"{pior} amostras (~{pior * intervalo:.0f} s)")
    print(f"Falhas por tipo: {erros or '-'}")
    print(f"Reinícios do serviço (pid novo): {reinicios}; node saiu de Online {quedas} vez(es) (E6)")
    comum.imprimir_resumo("Tempo de resposta HTTP", [_num(l["http_ms"]) for l in linhas if _num(l["http_ms"])], "ms")
    comum.imprimir_resumo("CPU do DroidServer", [_num(l["cpu_droidserver"]) for l in linhas
                                                  if _num(l["cpu_droidserver"]) is not None], "%")
    comum.imprimir_resumo("CPU do Worker", [_num(l["cpu_worker"]) for l in linhas
                                             if _num(l["cpu_worker"]) is not None], "%")
    comum.imprimir_resumo("RAM do aparelho", [_num(l["ram_pct"]) for l in linhas if _num(l["ram_pct"])], "%")
    comum.imprimir_resumo("RSS do agente (E10)", [_num(l["rss_agente_kb"]) / 1024 for l in linhas
                                                   if _num(l["rss_agente_kb"])], "MB")
    comum.imprimir_resumo("RSS do supervisord (E10)", [_num(l["rss_supervisord_kb"]) / 1024 for l in linhas
                                                        if _num(l["rss_supervisord_kb"])], "MB")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--worker", default="demo_api")
    ap.add_argument("--porta", type=int, default=8080)
    ap.add_argument("--horas", type=float, default=24)
    ap.add_argument("--intervalo", type=float, default=10)
    ap.add_argument("--ssh-intervalo", type=float, default=300)
    ap.add_argument("--resumo", metavar="CSV", help="só resume um CSV já coletado (mesmo incompleto)")
    args = ap.parse_args()
    if args.resumo:
        resumir(args.resumo)
    else:
        coletar(args)


if __name__ == "__main__":
    main()
