"""Uso do node ao vivo (1 amostra por segundo) enquanto alguém assiste.

O ciclo normal do agente mede a cada 10 s e grava no registro. Com a aba
Monitor aberta, o painel assina este fluxo e recebe CPU/RAM a cada segundo;
a medição aqui é só o instantâneo (leitura de /proc, sem `supervisorctl` nem
`top`) e nada é gravado no registro.

A assinatura vence sozinha depois de `validade` segundos sem ser renovada: o
host renova a cada sync enquanto houver navegador assistindo, então um
cancelamento perdido (ou o painel fechado sem aviso) não deixa o celular
medindo a cada segundo para sempre.
"""

import logging
import threading
import time

log = logging.getLogger("node")

INTERVALO = 1.0
VALIDADE = 30.0


class AoVivo:
    """Thread que chama `medir()` a cada `intervalo` e entrega a `enviar(amostra)`.

    `medir` pode guardar estado entre chamadas (ex.: o delta de CPU); `reiniciar`
    é chamado no começo de cada assinatura para a primeira amostra medir só o
    último segundo, e não o tempo desde a assinatura anterior.
    """

    def __init__(self, medir, enviar, reiniciar=lambda: None, intervalo=INTERVALO,
                 validade=VALIDADE, relogio=time.monotonic):
        self.medir = medir
        self.enviar = enviar
        self.reiniciar = reiniciar
        self.intervalo = intervalo
        self.validade = validade
        self._relogio = relogio
        self._lock = threading.Lock()
        self._parar = None          # threading.Event da thread ativa
        self._renovado_em = 0.0

    def assinar(self):
        """Liga o fluxo (ou renova a validade, se já estiver ligado)."""
        with self._lock:
            self._renovado_em = self._relogio()
            if self._parar is not None:
                return
            parar = self._parar = threading.Event()
        threading.Thread(target=self._rodar, args=(parar,), daemon=True).start()

    def cancelar(self):
        with self._lock:
            parar, self._parar = self._parar, None
        if parar:
            parar.set()

    def ativo(self):
        with self._lock:
            return self._parar is not None

    def _vencido(self):
        with self._lock:
            return self._relogio() - self._renovado_em > self.validade

    def _rodar(self, parar):
        try:
            self.reiniciar()
        except Exception:
            log.exception("[-] Falha ao preparar o uso ao vivo")
        while not parar.wait(self.intervalo):
            if self._vencido():
                log.info("[*] Uso ao vivo encerrado: ninguém renovou a assinatura.")
                with self._lock:
                    if self._parar is parar:
                        self._parar = None
                return
            try:
                amostra = self.medir()
            except Exception:
                log.exception("[-] Falha ao medir o uso ao vivo")
                continue
            try:
                self.enviar(amostra)
            except Exception as e:
                log.debug("Falha ao enviar o uso ao vivo: %s", e)
