"""Funções comuns aos experimentos da Fase 3 (nota 09 do vault).

Configuração por variáveis de ambiente:
  DROID_HOST_URL       URL do painel (padrão http://localhost:5050)
  DROID_PANEL_PASSWORD senha do painel, se o Host exigir login
  DROID_NODE_IP        IP do celular (padrão: o primeiro node Online)
  DROID_SSH            destino SSH do celular, ex.: "-p 8022 192.168.1.5"
                       (usado só pelos experimentos que rodam comandos no aparelho)

Os dados brutos vão para bench/resultados/<experimento>_<data>.csv.
"""

import csv
import math
import os
import shlex
import statistics
import subprocess
import sys
import time
from datetime import datetime

import requests

RAIZ = os.path.dirname(os.path.abspath(__file__))
PASTA_RESULTADOS = os.path.join(RAIZ, "resultados")
HOST_URL = os.getenv("DROID_HOST_URL", "http://localhost:5050").rstrip("/")


# ---------------------------------------------------------------------------
# Painel (HTTP)
# ---------------------------------------------------------------------------

def sessao_painel():
    """requests.Session já logada no painel (se houver senha)."""
    s = requests.Session()
    senha = os.getenv("DROID_PANEL_PASSWORD")
    if senha:
        r = s.post(f"{HOST_URL}/login", data={"senha": senha}, allow_redirects=False, timeout=10)
        if r.status_code != 302:
            sys.exit("Login no painel falhou: confira DROID_PANEL_PASSWORD.")
    r = s.get(f"{HOST_URL}/api/nodes", timeout=10)
    if r.status_code == 401:
        sys.exit("O painel exige login: defina DROID_PANEL_PASSWORD.")
    r.raise_for_status()
    return s


def ip_do_node(s):
    ip = os.getenv("DROID_NODE_IP")
    if ip:
        return ip
    nodes = s.get(f"{HOST_URL}/api/nodes", timeout=10).json()
    online = [ip for ip, n in nodes.items() if n.get("status") == "Online"]
    if not online:
        sys.exit("Nenhum node Online no painel.")
    return online[0]


def estado_node(s, ip):
    r = s.get(f"{HOST_URL}/api/node/{ip}", timeout=10)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Celular (SSH)
# ---------------------------------------------------------------------------

def ssh(comando, timeout=600):
    """Roda um comando no Termux do celular. Devolve (código, stdout)."""
    destino = os.getenv("DROID_SSH")
    if not destino:
        sys.exit('Defina DROID_SSH, ex.: DROID_SSH="-p 8022 192.168.1.5"')
    proc = subprocess.run(["ssh", "-o", "BatchMode=yes", *shlex.split(destino), comando],
                          capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout


# ---------------------------------------------------------------------------
# CSV e estatística
# ---------------------------------------------------------------------------

def arquivo_csv(experimento):
    os.makedirs(PASTA_RESULTADOS, exist_ok=True)
    return os.path.join(PASTA_RESULTADOS, f"{experimento}_{datetime.now():%Y%m%d_%H%M%S}.csv")


class GravadorCSV:
    """Grava linha a linha (flush): um experimento interrompido não perde dados."""

    def __init__(self, caminho, campos):
        self.caminho = caminho
        self._f = open(caminho, "w", newline="", encoding="utf-8")
        self._w = csv.DictWriter(self._f, fieldnames=campos)
        self._w.writeheader()
        self._f.flush()

    def linha(self, **valores):
        self._w.writerow(valores)
        self._f.flush()

    def fechar(self):
        self._f.close()


def percentil(valores, p):
    """Percentil por interpolação linear (mesmo método do numpy padrão)."""
    v = sorted(valores)
    if not v:
        return float("nan")
    k = (len(v) - 1) * p / 100
    i = math.floor(k)
    j = min(i + 1, len(v) - 1)
    return v[i] + (v[j] - v[i]) * (k - i)


def resumo(valores):
    """n, média, desvio-padrão, IC 95% da média, mediana, p95, p99, mín, máx."""
    v = [x for x in valores if x is not None and not math.isnan(x)]
    n = len(v)
    if not n:
        return {"n": 0}
    media = statistics.fmean(v)
    dp = statistics.stdev(v) if n > 1 else 0.0
    # t de Student para 95% (bicaudal); para n > 30, ~1,96
    t = {2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776, 6: 2.571, 7: 2.447, 8: 2.365,
         9: 2.306, 10: 2.262, 11: 2.228, 12: 2.201, 15: 2.145, 20: 2.093, 25: 2.064,
         30: 2.045}
    tc = t.get(n) or (1.96 if n > 30 else t[min(t, key=lambda k: abs(k - n))])
    ic = tc * dp / math.sqrt(n) if n > 1 else 0.0
    return {"n": n, "media": media, "dp": dp, "ic95": ic, "mediana": statistics.median(v),
            "p95": percentil(v, 95), "p99": percentil(v, 99), "min": min(v), "max": max(v)}


def imprimir_resumo(titulo, valores, unidade):
    r = resumo(valores)
    if not r["n"]:
        print(f"{titulo}: sem amostras")
        return r
    print(f"{titulo} (n={r['n']}): média {r['media']:.2f} ± {r['ic95']:.2f} {unidade} (IC 95%), "
          f"dp {r['dp']:.2f} | mediana {r['mediana']:.2f} | p95 {r['p95']:.2f} | p99 {r['p99']:.2f} | "
          f"mín {r['min']:.2f} | máx {r['max']:.2f}")
    return r


def agora():
    return time.time()


def carimbo():
    return datetime.now().isoformat(timespec="seconds")
