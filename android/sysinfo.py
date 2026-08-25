"""Leitura de uso de CPU e memória do dispositivo via /proc (sem dependências).

Funciona em Termux/Android: /proc/stat e /proc/meminfo refletem o uso do
dispositivo inteiro, do ponto de vista do kernel Linux.
"""

import time

STAT_FILE = '/proc/stat'
MEMINFO_FILE = '/proc/meminfo'


def _read_cpu():
    """Lê os contadores de CPU do /proc/stat. Retorna (total, idle) ou None."""
    try:
        with open(STAT_FILE) as f:
            line = f.readline()
    except OSError:
        return None

    parts = line.split()
    if not parts or parts[0] != 'cpu':
        return None

    try:
        values = [int(v) for v in parts[1:9]]
    except ValueError:
        return None
    if len(values) < 5:
        return None

    # idle + iowait contam como ociosidade
    idle = values[3] + values[4]
    return sum(values), idle


def _read_mem():
    """Lê memória total/disponível do /proc/meminfo em bytes. Retorna (total, available)."""
    try:
        with open(MEMINFO_FILE) as f:
            lines = f.readlines()
    except OSError:
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
        return {'cpu': cpu, 'mem': mem}
