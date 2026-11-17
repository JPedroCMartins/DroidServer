"""Leitura de uso de CPU e memória do dispositivo via /proc (sem dependências).

Funciona em Termux/Android: /proc/stat e /proc/meminfo refletem o uso do
dispositivo inteiro, do ponto de vista do kernel Linux.

Em dispositivos com SELinux restritivo, /proc/stat pode ser bloqueado — nesse
caso usamos o `top` do busybox como fallback.
"""

import logging
import os
import subprocess
import time

log = logging.getLogger("sysinfo")

STAT_FILE = '/proc/stat'
MEMINFO_FILE = '/proc/meminfo'
PROC_DIR = '/proc'

try:
    CLK_TCK = os.sysconf('SC_CLK_TCK')
except (ValueError, OSError, AttributeError):
    CLK_TCK = 100


def _read_cpu():
    """Lê os contadores de CPU do /proc/stat. Retorna (total, idle) ou None."""
    try:
        with open(STAT_FILE) as f:
            line = f.readline()
    except OSError as e:
        log.warning("Falha ao ler %s: %s", STAT_FILE, e)
        return None

    parts = line.split()
    if not parts or parts[0] != 'cpu':
        log.warning("Linha inesperada em %s: %r", STAT_FILE, line[:100])
        return None

    try:
        values = [int(v) for v in parts[1:9]]
    except ValueError as e:
        log.warning("Coluna não numérica em %s: %r (%s)", STAT_FILE, line[:100], e)
        return None

    # Tolera linhas curtas (alguns kernels expõem só user/nice/system/idle)
    if len(values) < 4:
        log.warning("Poucas colunas em %s (linha: %r)", STAT_FILE, line[:100])
        return None

    # formato: user nice system idle iowait irq softirq steal
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return sum(values), idle


def _read_mem():
    """Lê memória total/disponível do /proc/meminfo em bytes. Retorna (total, available)."""
    try:
        with open(MEMINFO_FILE) as f:
            lines = f.readlines()
    except OSError as e:
        log.warning("Falha ao ler %s: %s", MEMINFO_FILE, e)
        return None, None

    fields = {}
    for line in lines:
        key, _, resto = line.partition(':')
        try:
            fields[key] = int(resto.split()[0]) * 1024  # kB -> bytes
        except (ValueError, IndexError):
            pass

    total = fields.get('MemTotal', 0)
    available = fields.get('MemAvailable', fields.get('MemFree', 0))
    return total, available


def _cpu_via_top():
    """Fallback: usa `top -b -n 1` quando /proc/stat está bloqueado (SELinux)."""
    try:
        proc = subprocess.run(["top", "-b", "-n", "1"], capture_output=True, text=True, timeout=5)
    except Exception as e:
        log.warning("Falha ao executar top para CPU: %s", e)
        return None
    if proc.returncode != 0:
        return None
    for linha in proc.stdout.splitlines():
        if "%cpu" in linha and "%idle" in linha:
            try:
                partes = linha.split()
                total = float(next(p for p in partes if p.endswith("%cpu")).replace("%cpu", ""))
                idle = float(next(p for p in partes if p.endswith("%idle")).replace("%idle", ""))
            except (StopIteration, ValueError):
                return None
            if total <= 0:
                return None
            if idle >= total:
                # Em Android recente o toybox top também não lê /proc/stat e
                # mostra 100% ocioso com todos os campos zerados ("800%idle"),
                # mesmo com o próprio top em execução. Isso não é uma medição:
                # devolvemos None para o painel exibir "—" em vez de um falso 0%.
                log.debug("top sem dados de CPU (idle=%s de %s): tratado como indisponível", idle, total)
                return None
            return round(max(0.0, min(100.0, 100.0 * (total - idle) / total)), 1)
    return None


class SystemMonitor:
    """Calcula uso de CPU (% desde a última leitura) e memória do dispositivo."""

    def __init__(self):
        self._prev_cpu = _read_cpu()
        self._prev_ts = time.monotonic()
        self._avisou_cpu = False

    def sample(self):
        """Devolve {'cpu': pct_ou_None, 'mem': dict_ou_None}."""
        cpu = None
        atual = _read_cpu()
        if atual and self._prev_cpu:
            d_total = atual[0] - self._prev_cpu[0]
            d_idle = atual[1] - self._prev_cpu[1]
            if d_total > 0:
                cpu = round(100.0 * (d_total - d_idle) / d_total, 1)
            else:
                log.warning("Sem delta de CPU entre amostras (atual=%s, prev=%s)", atual, self._prev_cpu)
        elif atual is None:
            # /proc/stat bloqueado (SELinux) -> tenta o top do busybox
            cpu = _cpu_via_top()
            if cpu is None:
                # Avisa uma vez; nos próximos ciclos só em DEBUG (evita poluir o log a cada 10 s)
                nivel = logging.DEBUG if self._avisou_cpu else logging.WARNING
                log.log(nivel, "CPU do aparelho indisponível (%s ilegível e top sem resultado); "
                        "usando apenas a CPU dos processos do Termux", STAT_FILE)
                self._avisou_cpu = True
        self._prev_cpu = atual
        self._prev_ts = time.monotonic()

        total, available = _read_mem()
        mem = None
        if total:
            usado = max(total - available, 0)
            mem = {
                'total': total,
                'usado': usado,
                'percent': round(100.0 * usado / total, 1),
            }
        elif total == 0:
            log.debug("Memória indisponível (%s ilegível ou sem MemTotal)", MEMINFO_FILE)
        return {'cpu': cpu, 'mem': mem}


# ---------------------------------------------------------------------------
# CPU dos processos do Termux (agente + supervisor + workers)
# ---------------------------------------------------------------------------
# Sem root, o Android 16 nega /proc/stat e o top do sistema não mede a CPU
# global. Já o /proc/<pid>/stat dos processos do próprio app (mesmo UID do
# Termux) continua legível. Somando utime+stime desses processos entre duas
# amostras obtemos quanto da CPU do aparelho o DroidServer consumiu — no total
# e por worker. Validado no aparelho: cargas de 25/50/100% foram medidas como
# 22,9/49,8/87,5%. Não inclui outros apps do celular.

def ler_processos(proc_dir=None):
    """Lê os processos visíveis. Devolve {pid: (ppid, ticks_de_cpu)}."""
    proc_dir = proc_dir or PROC_DIR
    processos = {}
    try:
        nomes = os.listdir(proc_dir)
    except OSError:
        return processos
    for nome in nomes:
        if not nome.isdigit():
            continue
        try:
            with open(os.path.join(proc_dir, nome, 'stat')) as f:
                dados = f.read()
        except OSError:
            continue  # processo terminou ou não é visível
        # O nome do processo (campo 2) fica entre parênteses e pode ter espaços
        try:
            campos = dados.rsplit(')', 1)[1].split()
            ppid = int(campos[1])
            ticks = int(campos[11]) + int(campos[12])  # utime + stime
        except (IndexError, ValueError):
            continue
        processos[int(nome)] = (ppid, ticks)
    return processos


def descendentes(processos, raizes):
    """Conjunto com as raízes e todos os seus descendentes (pela árvore de ppid)."""
    filhos = {}
    for pid, (ppid, _) in processos.items():
        filhos.setdefault(ppid, []).append(pid)
    vistos = set()
    pilha = [p for p in raizes if p in processos]
    while pilha:
        pid = pilha.pop()
        if pid in vistos:
            continue
        vistos.add(pid)
        pilha.extend(filhos.get(pid, ()))
    return vistos


def _rss_kb(pid, proc_dir):
    try:
        with open(os.path.join(proc_dir, str(pid), 'status')) as f:
            for linha in f:
                if linha.startswith('VmRSS:'):
                    return int(linha.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return 0


def memoria_grupos(grupos, proc_dir=None):
    """{grupo: MB} somando o VmRSS das raízes e de todos os descendentes.

    O pid do Supervisor é só o wrapper do proot (~3 MB); a memória real do
    serviço está nos processos-filhos. Processo ilegível conta 0.
    """
    proc_dir = proc_dir or PROC_DIR
    processos = ler_processos(proc_dir)
    return {nome: round(sum(_rss_kb(p, proc_dir) for p in descendentes(processos, raizes)) / 1024, 1)
            for nome, raizes in grupos.items()}


class ProcessCPUMonitor:
    """Uso de CPU dos processos visíveis ao Termux, total e por grupo (worker).

    Os percentuais são relativos à capacidade do aparelho inteiro: 100% =
    todos os núcleos ocupados. Assim o total e os workers são comparáveis com
    o uso de CPU do dispositivo quando ele estiver disponível.
    """

    def __init__(self, proc_dir=None, ncpu=None, relogio=time.monotonic):
        self.proc_dir = proc_dir
        self.ncpu = ncpu or os.cpu_count() or 1
        self._relogio = relogio
        self._prev = ler_processos(self.proc_dir)
        self._prev_ts = relogio()

    def _pct(self, ticks, dt):
        if dt <= 0:
            return 0.0
        return round(max(0.0, min(100.0, 100.0 * ticks / CLK_TCK / dt / self.ncpu)), 1)

    def sample(self, grupos=None):
        """Devolve {'total': pct, 'grupos': {nome: pct}}.

        grupos: {nome: [pid_raiz, ...]} — cada grupo soma os processos raiz e
        seus descendentes (ex.: o pid do serviço no Supervisor e o da sessão
        de terminal de um worker).
        """
        atual = ler_processos(self.proc_dir)
        agora = self._relogio()
        dt = agora - self._prev_ts

        # Delta por processo. Um pid novo começou depois da amostra anterior,
        # então todo o seu tempo de CPU cabe no intervalo. Processos que
        # terminaram entre as amostras não são contabilizados (subestima
        # processos muito curtos).
        delta = {}
        for pid, (_, ticks) in atual.items():
            anterior = self._prev.get(pid)
            delta[pid] = max(ticks - anterior[1], 0) if anterior else ticks

        resultado = {
            'total': self._pct(sum(delta.values()), dt),
            'grupos': {},
        }
        for nome, raizes in (grupos or {}).items():
            pids = descendentes(atual, raizes)
            resultado['grupos'][nome] = self._pct(sum(delta[p] for p in pids), dt)

        self._prev, self._prev_ts = atual, agora
        return resultado
