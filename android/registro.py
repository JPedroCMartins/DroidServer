"""Registro local de métricas do Node, gravado no próprio celular.

O painel (Host) é só de gerenciamento e pode ser desligado a qualquer
momento. Por isso o agente grava aqui, a cada ciclo e com ou sem painel:
CPU do DroidServer, RAM do aparelho, memória do agente e do supervisord e,
para cada serviço, o estado no Supervisor, o pid e uma verificação HTTP na
porta declarada no run.sh (# droidserver: porta=N).

Formato: uma amostra JSON por linha (JSON Lines), com rotação por tamanho
(metricas.jsonl, .1, .2, ...; .1 é o mais recente dos antigos). O painel
lê daqui o histórico do gráfico quando volta a ser ligado, e a E7 do TCC
calcula a disponibilidade a partir destes arquivos.
"""

import json
import logging
import os
import threading
import time

import requests

log = logging.getLogger("node.registro")

ARQUIVO_NOME = "metricas.jsonl"
# 10 s por amostra, ~300 bytes cada: 2 MB ≈ 18 h; com 10 arquivos, cerca de uma semana.
MAX_BYTES = 2 * 1024 * 1024
BACKUPS = 10
HTTP_TIMEOUT = 3


def arquivo_padrao():
    pasta = os.getenv("DROID_REGISTRO_DIR") or os.path.join(
        os.path.expanduser("~"), ".config", "droidserver", "registro")
    return os.path.join(pasta, ARQUIVO_NOME)


class Registro:
    """Arquivo JSON Lines com rotação. Falhas de disco nunca derrubam o agente."""

    def __init__(self, arquivo=None, max_bytes=MAX_BYTES, backups=BACKUPS):
        self.arquivo = arquivo or arquivo_padrao()
        self.max_bytes = max_bytes
        self.backups = backups
        self._lock = threading.Lock()
        self._avisou = False

    def _rotacionar(self):
        for n in range(self.backups - 1, 0, -1):
            origem = f"{self.arquivo}.{n}"
            if os.path.exists(origem):
                os.replace(origem, f"{self.arquivo}.{n + 1}")
        os.replace(self.arquivo, f"{self.arquivo}.1")

    def gravar(self, amostra):
        amostra = dict(amostra)
        amostra.setdefault("t", round(time.time(), 1))
        linha = json.dumps(amostra, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._lock:
            try:
                os.makedirs(os.path.dirname(self.arquivo), exist_ok=True)
                tamanho = os.path.getsize(self.arquivo) if os.path.exists(self.arquivo) else 0
                if tamanho and tamanho + len(linha.encode()) > self.max_bytes:
                    self._rotacionar()
                with open(self.arquivo, "a", encoding="utf-8") as f:
                    f.write(linha)
                    f.flush()
                self._avisou = False
            except OSError as e:
                # avisa uma vez por sequência de falhas (disco cheio, permissão)
                if not self._avisou:
                    log.warning("[-] Não foi possível gravar o registro local '%s': %s", self.arquivo, e)
                    self._avisou = True

    def _arquivos(self):
        """Do mais antigo para o mais novo."""
        antigos = [f"{self.arquivo}.{n}" for n in range(self.backups, 0, -1)]
        return [a for a in antigos + [self.arquivo] if os.path.exists(a)]

    def ler(self, desde=None, ate=None):
        amostras = []
        for caminho in self._arquivos():
            try:
                with open(caminho, encoding="utf-8", errors="replace") as f:
                    for linha in f:
                        try:
                            a = json.loads(linha.replace("\0", ""))
                            t = float(a["t"])
                        except (ValueError, KeyError, TypeError):
                            continue  # linha cortada por queda de energia, por exemplo
                        if (desde is None or t >= desde) and (ate is None or t <= ate):
                            amostras.append(a)
            except OSError:
                continue
        return amostras

    def historico(self, desde, maximo=None):
        """Série compacta para o gráfico do painel: [{t, cpu, ram}]."""
        serie = [{"t": a["t"], "cpu": a.get("cpu_termux"), "ram": a.get("ram_pct")}
                 for a in self.ler(desde=desde)]
        return serie[-maximo:] if maximo else serie


def checar_http(porta, timeout=HTTP_TIMEOUT):
    """GET no serviço pela interface local. Disponível = resposta 2xx/3xx."""
    t0 = time.perf_counter()
    try:
        r = requests.get(f"http://127.0.0.1:{porta}/", timeout=timeout, allow_redirects=False)
    except requests.exceptions.RequestException as e:
        return {"http_ok": False, "http_status": None, "http_ms": None, "erro": type(e).__name__}
    return {"http_ok": 200 <= r.status_code < 400, "http_status": r.status_code,
            "http_ms": round((time.perf_counter() - t0) * 1000, 1), "erro": ""}


def ppid(pid, proc_dir="/proc"):
    """Processo pai (para achar o supervisord a partir do pid de um serviço)."""
    try:
        with open(os.path.join(proc_dir, str(pid), "stat")) as f:
            # o nome do processo pode ter espaços: os campos seguem o último ')'
            return int(f.read().rsplit(")", 1)[1].split()[1])
    except (OSError, ValueError, IndexError):
        return None
