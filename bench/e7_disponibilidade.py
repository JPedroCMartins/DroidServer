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
import glob
import json
import os
import shlex
import subprocess
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
    anterior = None
    for a in janela + [None]:
        t = a["t"] if a else fim
        if anterior is None and a is None:  # nenhuma amostra na janela
            base, faltam = inicio - intervalo, int((fim - inicio) / intervalo) + 1
        elif anterior is None:  # começo: só falta o que já devia ter sido gravado até a 1ª amostra
            base, faltam = t - intervalo * (int((t - inicio) / intervalo - 0.5) + 1), int((t - inicio) / intervalo - 0.5)
        elif a is None:  # fim: idem, da última amostra até o fim da janela
            base, faltam = anterior, max(0, int((fim - anterior) / intervalo - 0.5))
        else:  # entre duas amostras: as que deviam existir entre elas
            base, faltam = anterior, int((t - anterior) / intervalo + 0.5) - 1
        for k in range(1, max(0, faltam) + 1):
            linhas.append(_linha_vazia(base + k * intervalo, "sem_registro"))
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


def calcular(amostras, worker, inicio, fim, horas, intervalo, pasta=None):
    """Monta o CSV da janela, imprime o resumo e diz se a janela está completa."""
    linhas = montar_linhas(amostras, worker, inicio, fim, intervalo)
    # Menos registro que o pedido: avisa e não deixa o CSV parecer a E7 completa
    # (o gráfico usa o e7_disponibilidade_*.csv mais recente)
    completo = fim - inicio >= horas * 3600 * 0.99
    nome = "e7_disponibilidade" if completo else "parcial_e7_disponibilidade"
    if pasta:
        os.makedirs(pasta, exist_ok=True)
        caminho = os.path.join(pasta, f"{nome}_{datetime.now():%Y%m%d_%H%M%S}.csv")
    else:
        caminho = comum.arquivo_csv(nome)
    g = comum.GravadorCSV(caminho, CAMPOS)
    for l in linhas:
        g.linha(**{c: ("" if l.get(c) is None else l.get(c, "")) for c in CAMPOS})
    g.fechar()
    sem_painel = sum(1 for a in amostras if inicio <= a["t"] <= fim and a.get("painel") is not True)
    print(f"Janela: {datetime.fromtimestamp(inicio):%d/%m %H:%M} a {datetime.fromtimestamp(fim):%d/%m %H:%M}; "
          f"amostras com o painel desligado/inacessível: {sem_painel}")
    resumir(caminho)
    if not completo:
        pronto = datetime.fromtimestamp(inicio + horas * 3600)
        print(f"\n[!] PARCIAL: só há {(fim - inicio) / 3600:.2f} h de registro na janela, de {horas:g} h pedidas. "
              f"Resultado final a partir de {pronto:%d/%m %H:%M}.\n"
              f"    Este resultado foi salvo como parcial_* e não entra no gráfico da E7.")
    return caminho, completo


# ---------------------------------------------------------------------------
# Acompanhamento automático no próprio celular
#   PC:      --iniciar   copia este script, grava o início e liga o acompanhamento
#   celular: --acompanhar  atualiza progresso.txt a cada 15 min e grava o
#            resultado final ao completar as horas (depois termina)
#   PC:      --status    mostra o progresso; sem opções, usa o início gravado
# ---------------------------------------------------------------------------

PASTA_E7_CELULAR = "~/.config/droidserver/e7"
MARCADOR = "inicio.json"


def _pasta_e7_local():
    return os.path.expanduser(PASTA_E7_CELULAR)


def ler_registro_local():
    pasta = os.path.expanduser(PASTA_REGISTRO)
    partes = []
    for nome in [f"metricas.jsonl.{n}" for n in range(10, 0, -1)] + ["metricas.jsonl"]:
        try:
            with open(os.path.join(pasta, nome), encoding="utf-8", errors="replace") as f:
                partes.append(f.read())
        except OSError:
            pass
    return "".join(partes)


def acompanhar(args):
    """Roda no celular (Termux), em segundo plano, até completar a E7."""
    pasta = _pasta_e7_local()
    with open(os.path.join(pasta, MARCADOR), encoding="utf-8") as f:
        m = json.load(f)
    inicio, horas, worker = m["inicio"], m["horas"], m["worker"]
    fim_previsto = inicio + horas * 3600
    import contextlib
    import io
    while True:
        agora = time.time()
        final = agora >= fim_previsto
        amostras = ler_amostras(ler_registro_local())
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            if amostras:
                calcular(amostras, worker, inicio, min(agora, fim_previsto), horas, args.intervalo,
                         pasta=os.path.join(pasta, "final" if final else "parcial"))
            else:
                print("Registro vazio.")
        texto = (f"E7 no celular — {worker}, {horas:g} h, de {datetime.fromtimestamp(inicio):%d/%m %H:%M} "
                 f"a {datetime.fromtimestamp(fim_previsto):%d/%m %H:%M}\n"
                 f"Atualizado em {datetime.now():%d/%m %H:%M}: {'CONCLUÍDA' if final else 'em andamento'}\n\n"
                 + saida.getvalue())
        with open(os.path.join(pasta, "resultado.txt" if final else "progresso.txt"), "w", encoding="utf-8") as f:
            f.write(texto)
        if final:
            print("E7 concluída: resultado.txt gravado.", flush=True)
            return
        # mantém só o parcial mais recente
        for velho in sorted(glob.glob(os.path.join(pasta, "parcial", "*.csv")))[:-1]:
            os.remove(velho)
        time.sleep(min(args.acompanhar_cada * 60, max(1.0, fim_previsto - time.time())))


SCRIPTS = ("e7_disponibilidade.py", "comum.py")


def _ligar_acompanhamento():
    aqui = os.path.dirname(os.path.abspath(__file__))
    destino = os.getenv("DROID_SSH")
    if not destino:
        raise SystemExit('Defina DROID_SSH, ex.: DROID_SSH="-p 8022 192.168.1.100"')
    opcoes = shlex.split(destino)
    porta = opcoes[opcoes.index("-p") + 1] if "-p" in opcoes else "22"
    host = [o for o in opcoes if not o.startswith("-") and o != porta][-1]
    comum.ssh("mkdir -p ~/DroidServer/bench " + PASTA_E7_CELULAR, timeout=30)
    subprocess.run(["scp", "-q", "-o", "BatchMode=yes", "-P", porta,
                    *[os.path.join(aqui, n) for n in SCRIPTS], f"{host}:DroidServer/bench/"], check=True)
    # setsid + nohup: segue rodando depois que o SSH fecha
    comum.ssh(f"pkill -f 'e7_disponibilidade.py --acompanhar' ; cd ~/DroidServer/bench && "
              f"setsid nohup python3 e7_disponibilidade.py --acompanhar > {PASTA_E7_CELULAR}/acompanhar.log 2>&1 "
              "< /dev/null & sleep 2; pgrep -f 'e7_disponibilidade.py --acompanhar' >/dev/null && echo ok",
              timeout=60)


def iniciar(args):
    codigo, atual = comum.ssh(f"cat {PASTA_E7_CELULAR}/{MARCADOR} 2>/dev/null", timeout=30)
    if atual.strip() and not args.novo:
        m = json.loads(atual)
        raise SystemExit(f"Já há uma E7 iniciada em {datetime.fromtimestamp(m['inicio']):%d/%m %H:%M}. "
                         "Use --retomar para religar o acompanhamento ou --novo para começar outra.")
    inicio = time.time()
    m = {"inicio": round(inicio, 1), "horas": args.horas, "worker": args.worker}
    comum.ssh(f"mkdir -p {PASTA_E7_CELULAR} && rm -f {PASTA_E7_CELULAR}/resultado.txt "
              f"{PASTA_E7_CELULAR}/progresso.txt && echo '{json.dumps(m)}' > {PASTA_E7_CELULAR}/{MARCADOR}",
              timeout=30)
    _ligar_acompanhamento()
    print(f"E7 iniciada em {datetime.fromtimestamp(inicio):%d/%m %H:%M} ({args.worker}, {args.horas:g} h); "
          f"termina em {datetime.fromtimestamp(inicio + args.horas * 3600):%d/%m %H:%M}.")
    print("O PC e o painel podem ser desligados. Progresso: uv run bench/e7_disponibilidade.py --status")


def retomar(args):
    _ligar_acompanhamento()
    print("Acompanhamento religado no celular (o registro não parou; nada se perdeu).")


def status(args):
    _, saida = comum.ssh(f"cd {PASTA_E7_CELULAR} 2>/dev/null && (cat resultado.txt 2>/dev/null || "
                         "cat progresso.txt 2>/dev/null || echo 'Ainda sem progresso (o 1º sai em instantes).'); "
                         "pgrep -f 'e7_disponibilidade.py --acompanhar' >/dev/null && echo '[acompanhamento rodando]' "
                         "|| echo '[acompanhamento parado: se a E7 não terminou, use --retomar]'", timeout=60)
    print(saida or "Nenhuma E7 iniciada no celular.")


def marcador_remoto():
    try:
        _, texto = comum.ssh(f"cat {PASTA_E7_CELULAR}/{MARCADOR} 2>/dev/null", timeout=30)
        return json.loads(texto) if texto.strip() else None
    except (ValueError, SystemExit):
        return None


def do_celular(args):
    amostras = ler_amostras(open(args.registro, encoding="utf-8").read() if args.registro else baixar_registro())
    if not amostras:
        raise SystemExit("Registro vazio.")
    horas, worker = args.horas, args.worker
    if args.inicio:
        inicio = datetime.fromisoformat(args.inicio).timestamp()
    elif not args.registro and (m := marcador_remoto()):
        # início gravado no celular pelo --iniciar
        inicio, horas, worker = m["inicio"], m["horas"], m["worker"]
        print(f"Usando a E7 iniciada em {datetime.fromtimestamp(inicio):%d/%m %H:%M} ({worker}, {horas:g} h).")
    else:  # as últimas --horas registradas
        inicio = max(amostras[-1]["t"] - horas * 3600, amostras[0]["t"])
    fim = min(inicio + horas * 3600, amostras[-1]["t"])
    calcular(amostras, worker, inicio, fim, horas, args.intervalo)


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
    ap.add_argument("--iniciar", action="store_true", help="marca o início no celular e liga o acompanhamento lá")
    ap.add_argument("--novo", action="store_true", help="com --iniciar: descarta a E7 anterior e começa outra")
    ap.add_argument("--retomar", action="store_true", help="religa o acompanhamento (ex.: depois de um reboot)")
    ap.add_argument("--status", action="store_true", help="mostra o progresso calculado no celular")
    ap.add_argument("--acompanhar", action="store_true", help=argparse.SUPPRESS)  # roda no celular
    ap.add_argument("--acompanhar-cada", type=float, default=15, help=argparse.SUPPRESS)  # minutos
    args = ap.parse_args()
    if args.acompanhar:
        acompanhar(args)
    elif args.iniciar:
        iniciar(args)
    elif args.retomar:
        retomar(args)
    elif args.status:
        status(args)
    elif args.resumo:
        resumir(args.resumo)
    elif args.pelo_pc:
        coletar(args)
    else:
        do_celular(args)


if __name__ == "__main__":
    main()
