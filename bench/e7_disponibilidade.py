# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""E7 — Disponibilidade de uma aplicação num Worker (QP3 / H1), com E6 e E10.

Modo padrão (desde 17/11): os dados vêm do **registro local do celular**.
O agente do Node grava a cada 10 s, com ou sem painel, o estado de cada
serviço (Supervisor, pid) e um GET na porta declarada no run.sh, além da
CPU, da RAM e da memória do agente e do supervisord
(~/.config/droidserver/registro/metricas.jsonl). O PC e o painel podem ficar
desligados durante toda a medição. No fim, este script baixa o registro por
SSH, recorta a janela pedida e gera o mesmo CSV do modo antigo:
  - amostras que faltam no registro (agente parado, aparelho desligado,
    Android congelando o Termux) entram como indisponíveis ("sem_registro");
  - reinício = pid novo do serviço; E6 = lacunas do próprio agente;
  - E10 = RSS do agente e do supervisord.

Uso:
  # anote a hora de início e deixe o celular parado; depois de 24 h:
  DROID_SSH="-p 8022 192.168.1.100" uv run bench/e7_disponibilidade.py \\
      --worker demo_api --inicio "2026-11-17 01:00" --horas 24
  uv run bench/e7_disponibilidade.py --resumo bench/resultados/e7_disponibilidade_<data>.csv

Modo antigo (--pelo-pc, rodadas 1 e 2 de 16/11): um script no PC faz o GET pela
rede e lê o estado pelo painel; desligar o PC interrompe a medição.
"""

import argparse
import csv
import json
import os
import time
from datetime import datetime

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
    # Tolera o fim de arquivo corrompido por uma queda de energia (bytes nulos,
    # última linha pela metade): só entram linhas com carimbo de tempo válido.
    with open(caminho, encoding="utf-8", errors="replace") as f:
        linhas = [l for l in csv.DictReader(line.replace("\0", "") for line in f)
                  if _num(l.get("t")) is not None]
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


# ---------------------------------------------------------------------------
# Modo padrão: registro local do celular
# ---------------------------------------------------------------------------

PASTA_REGISTRO = "~/.config/droidserver/registro"


def baixar_registro():
    """Concatena metricas.jsonl.N ... .1 e metricas.jsonl (do mais antigo ao mais novo)."""
    cmd = (f"cd {PASTA_REGISTRO} && for n in 10 9 8 7 6 5 4 3 2 1; do "
           "[ -f metricas.jsonl.$n ] && cat metricas.jsonl.$n; done; cat metricas.jsonl")
    codigo, saida = comum.ssh(cmd, timeout=300)
    if codigo != 0 and not saida:
        raise SystemExit("Não foi possível ler o registro no celular (o agente já foi atualizado?).")
    bruto = comum.arquivo_csv("e7_registro").replace(".csv", ".jsonl")
    with open(bruto, "w", encoding="utf-8") as f:
        f.write(saida)
    print(f"Registro bruto salvo em {bruto}")
    return saida


def ler_amostras(texto):
    amostras = []
    for linha in texto.splitlines():
        try:
            a = json.loads(linha.replace("\0", ""))
            a["t"] = float(a["t"])
        except (ValueError, KeyError, TypeError):
            continue
        amostras.append(a)
    return sorted(amostras, key=lambda a: a["t"])


def _linha_vazia(t, erro):
    return {"carimbo": datetime.fromtimestamp(t).isoformat(timespec="seconds"), "t": round(t, 1),
            "http_ok": False, "erro": erro, "node_status": erro}


def montar_linhas(amostras, worker, inicio, fim, intervalo=10.0):
    """Linhas do CSV da E7 na janela [inicio, fim], com as lacunas preenchidas."""
    janela = [a for a in amostras if inicio <= a["t"] <= fim]
    linhas = []
    anterior = inicio - intervalo  # lacuna no começo também conta
    for a in janela + [None]:
        t = a["t"] if a else fim + intervalo
        faltam = int((t - anterior) / intervalo + 0.5) - 1  # amostras que deviam existir entre as duas
        for k in range(1, faltam + 1):
            linhas.append(_linha_vazia(anterior + k * intervalo, "sem_registro"))
        if a is None:
            break
        sv = (a.get("servicos") or {}).get(worker) or {}
        linhas.append({
            "carimbo": datetime.fromtimestamp(t).isoformat(timespec="seconds"), "t": round(t, 1),
            "http_ok": sv.get("http_ok") is True, "http_status": sv.get("http_status") or "",
            "http_ms": sv.get("http_ms") or "", "erro": sv.get("erro") or ("" if sv else "worker_ausente"),
            "node_status": "Online", "cpu_droidserver": a.get("cpu_termux"), "cpu_worker": sv.get("cpu"),
            "ram_pct": a.get("ram_pct"), "servico_estado": sv.get("estado"), "servico_pid": sv.get("pid"),
            "servico_uptime": sv.get("uptime"), "rss_agente_kb": a.get("rss_agente_kb"),
            "rss_supervisord_kb": a.get("rss_supervisord_kb"),
        })
        anterior = t
    return linhas


def do_celular(args):
    amostras = ler_amostras(open(args.registro, encoding="utf-8").read() if args.registro else baixar_registro())
    if not amostras:
        raise SystemExit("Registro vazio.")
    if args.inicio:
        inicio = datetime.fromisoformat(args.inicio).timestamp()
        fim = min(inicio + args.horas * 3600, amostras[-1]["t"])
    else:  # as últimas --horas registradas
        fim = amostras[-1]["t"]
        inicio = max(fim - args.horas * 3600, amostras[0]["t"])
    linhas = montar_linhas(amostras, args.worker, inicio, fim, args.intervalo)
    # Menos registro que o pedido: avisa e não deixa o CSV parecer a E7 completa
    # (o gráfico usa o e7_disponibilidade_*.csv mais recente)
    completo = fim - inicio >= args.horas * 3600 * 0.99
    caminho = comum.arquivo_csv("e7_disponibilidade" if completo else "parcial_e7_disponibilidade")
    g = comum.GravadorCSV(caminho, CAMPOS)
    for l in linhas:
        g.linha(**{c: ("" if l.get(c) is None else l.get(c, "")) for c in CAMPOS})
    g.fechar()
    sem_painel = sum(1 for a in amostras if inicio <= a["t"] <= fim and a.get("painel") is not True)
    print(f"Janela: {datetime.fromtimestamp(inicio):%d/%m %H:%M} a {datetime.fromtimestamp(fim):%d/%m %H:%M}; "
          f"amostras com o painel desligado/inacessível: {sem_painel}")
    resumir(caminho)
    if not completo:
        pronto = datetime.fromtimestamp(inicio + args.horas * 3600)
        print(f"\n[!] PARCIAL: só há {(fim - inicio) / 3600:.2f} h de registro na janela, de {args.horas:g} h pedidas. "
              f"Deixe o celular parado e rode de novo a partir de {pronto:%d/%m %H:%M}.\n"
              f"    Este resultado foi salvo como parcial_* e não entra no gráfico da E7.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--worker", default="demo_api")
    ap.add_argument("--porta", type=int, default=8080)
    ap.add_argument("--horas", type=float, default=24)
    ap.add_argument("--intervalo", type=float, default=10)
    ap.add_argument("--ssh-intervalo", type=float, default=300)
    ap.add_argument("--resumo", metavar="CSV", help="só resume um CSV já coletado (mesmo incompleto)")
    ap.add_argument("--inicio", help='início da janela, ex.: "2026-11-17 01:00" (padrão: últimas --horas)')
    ap.add_argument("--registro", metavar="JSONL", help="usa um registro já baixado em vez de buscar por SSH")
    ap.add_argument("--pelo-pc", action="store_true", help="modo antigo: mede a partir do PC, pelo painel")
    args = ap.parse_args()
    if args.resumo:
        resumir(args.resumo)
    elif args.pelo_pc:
        coletar(args)
    else:
        do_celular(args)


if __name__ == "__main__":
    main()
