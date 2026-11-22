"""Uso de armazenamento do node: disco do aparelho e quanto cada worker ocupa.

- `disco()` lê o espaço da partição de dados do Termux (barato, sempre ao vivo);
- `medir()` soma o tamanho de cada worker (rootfs do container ou pasta do
  PostgreSQL, mais os logs do serviço) e o do próprio DroidServer.

Percorrer um rootfs inteiro no celular custa caro (dezenas de milhares de
arquivos), então o `Medidor` guarda o último resultado e só refaz a medição
numa thread em segundo plano, no máximo a cada `intervalo` segundos ou
quando o painel pede ("Recalcular").
"""

import glob
import logging
import os
import shutil
import threading
import time

import banco
import servico

log = logging.getLogger("node.armazenamento")

INTERVALO = 10 * 60  # idade máxima da medição em cache


def disco(caminho=None):
    """{total, usado, livre, percent} da partição onde fica o Termux."""
    caminho = caminho or servico._prefix()
    if not os.path.exists(caminho):
        caminho = os.path.expanduser("~")
    try:
        u = shutil.disk_usage(caminho)
    except OSError:
        return None
    return {"total": u.total, "usado": u.used, "livre": u.free,
            "percent": round(100.0 * u.used / u.total, 1) if u.total else None}


def _ocupado(st):
    """Bytes alocados no disco (como o `du`); o tamanho lógico se não houver blocos."""
    blocos = getattr(st, "st_blocks", None)
    return blocos * 512 if blocos is not None else st.st_size


def tamanho_dir(caminho, _vistos=None):
    """Espaço ocupado por uma pasta, sem seguir links e ignorando o que não dá para ler.

    Arquivos com vários hard links são contados uma vez só.
    """
    vistos = set() if _vistos is None else _vistos
    total = 0
    pilha = [caminho]
    while pilha:
        atual = pilha.pop()
        try:
            entradas = os.scandir(atual)
        except OSError:
            continue
        with entradas:
            for e in entradas:
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if st.st_nlink > 1 and not e.is_dir(follow_symlinks=False):
                    chave = (st.st_dev, st.st_ino)
                    if chave in vistos:
                        continue
                    vistos.add(chave)
                total += _ocupado(st)
                if e.is_dir(follow_symlinks=False):
                    pilha.append(e.path)
    return total


def tamanho_arquivos(caminhos):
    total = 0
    for c in set(caminhos):
        try:
            total += _ocupado(os.lstat(c))
        except OSError:
            pass
    return total


def logs_do_servico(alias):
    """Log atual do serviço, as rotações e os de versões antigas."""
    arquivos = []
    for base in [servico.arquivo_log(alias)] + servico.logs_antigos(alias):
        arquivos.append(base)
        arquivos.extend(glob.glob(glob.escape(base) + ".*"))
    return arquivos


def medir(aliases, pastas_droidserver=()):
    """{workers: {alias: {tipo, dados, logs, total}}, droidserver, workers_total}."""
    workers = {}
    for alias in sorted(set(aliases)):
        if not servico.alias_valido(alias):
            continue
        if banco.existe(alias):
            tipo, dados = "postgres", tamanho_dir(banco.diretorio(alias))
        else:
            raiz = servico.rootfs(alias)
            tipo, dados = "linux", tamanho_dir(raiz) if raiz else 0
        logs = tamanho_arquivos(logs_do_servico(alias))
        workers[alias] = {"tipo": tipo, "dados": dados, "logs": logs, "total": dados + logs}

    # Pastas do agente (registro, log, pareamento): uma pasta dentro da outra conta uma vez
    pastas = sorted({os.path.realpath(p) for p in pastas_droidserver if p and os.path.isdir(p)})
    raizes = [p for p in pastas if not any(p != o and p.startswith(o + os.sep) for o in pastas)]
    droidserver = sum(tamanho_dir(p) for p in raizes)
    droidserver += tamanho_arquivos(logs_do_servico(servico.TUNNEL))
    return {"workers": workers, "droidserver": droidserver,
            "workers_total": sum(w["total"] for w in workers.values())}


class Medidor:
    """Cache da medição, refeita em segundo plano (uma por vez)."""

    def __init__(self, aliases, pastas=lambda: (), intervalo=INTERVALO, relogio=time.time):
        self._aliases = aliases      # função: aliases dos workers instalados
        self._pastas = pastas        # função: pastas do DroidServer
        self.intervalo = intervalo
        self._relogio = relogio
        self._lock = threading.Lock()
        self._resultado = None
        self._medido_em = None
        self._duracao = None
        self._medindo = False

    def estado(self):
        """Última medição; dispara uma nova se estiver velha (ou nunca feita)."""
        with self._lock:
            velho = self._medido_em is None or self._relogio() - self._medido_em >= self.intervalo
        if velho:
            self.recalcular()
        with self._lock:
            r = self._resultado or {"workers": {}, "droidserver": None, "workers_total": None}
            return {**r, "workers": dict(r["workers"]), "medido_em": self._medido_em,
                    "duracao_s": self._duracao, "medindo": self._medindo}

    def recalcular(self):
        """Inicia uma medição em segundo plano. False se já há uma em andamento."""
        with self._lock:
            if self._medindo:
                return False
            self._medindo = True
        threading.Thread(target=self._medir, daemon=True).start()
        return True

    def esquecer(self, alias):
        """Tira um worker apagado da medição em cache."""
        with self._lock:
            if self._resultado and alias in self._resultado["workers"]:
                w = self._resultado["workers"].pop(alias)
                self._resultado["workers_total"] -= w["total"]

    def _medir(self):
        try:
            # Prioridade baixa: medir o disco não pode atrasar os serviços
            os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 10)
        except (AttributeError, OSError):
            pass
        inicio = time.monotonic()
        try:
            resultado = medir(self._aliases(), self._pastas())
        except Exception:
            log.exception("[-] Falha ao medir o armazenamento")
            resultado = None
        with self._lock:
            if resultado is not None:
                self._resultado = resultado
                self._medido_em = round(self._relogio(), 1)
                self._duracao = round(time.monotonic() - inicio, 2)
            self._medindo = False
