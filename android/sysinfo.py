"""Leitura de uso de CPU e memória do dispositivo via /proc (sem dependências).

Funciona em Termux/Android: /proc/stat e /proc/meminfo refletem o uso do
dispositivo inteiro, do ponto de vista do kernel Linux.
"""

import logging
import time

log = logging.getLogger("sysinfo")

STAT_FILE = '/proc/stat'
MEMINFO_FILE = '/proc/meminfo'


def _read_cpu():
    """Lê os contadores de CPU do /proc/stat. Retorna (total, idle) ou None."""
    try:
        with open(STAT_FILE) as f:
            line = f.readline()
    except OSError as e:
        log.debug("Falha ao ler %s: %s", STAT_FILE, e)
        return None

    parts = line.split()
    if not parts or parts[0] != 'cpu':
        log.debug("Linha inesperada em %s: %r", STAT_FILE, line[:100])
        return None

    try:
        values = [int(v) for v in parts[1:9]]
    except ValueError as e:
        log.debug("Coluna não numérica em %s: %r (%s)", STAT_FILE, line[:100], e)
        return None

    # Tolera linhas curtas (alguns kernels expõem só user/nice/system/idle)
    if len(values) < 4:
        log.debug("Poucas colunas em %s: %r", STAT_FILE, line[:100])
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
        log.debug("Falha ao ler %s: %s", MEMINFO_FILE, e)
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


class SystemMonitor:
    """Calcula uso de CPU (% desde a última leitura) e memória do dispositivo."""

    def __init__(self):
        self._prev_cpu = _read_cpu()
        self._prev_ts = time.monotonic()

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
                log.debug("Sem delta de CPU entre amostras (atual=%s, prev=%s)", atual, self._prev_cpu)
        elif atual is None:
            log.debug("CPU indisponível nesta amostra (%s ilegível ou mal formatado)", STAT_FILE)
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
