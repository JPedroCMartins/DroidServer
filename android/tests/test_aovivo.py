import threading
import time

import aovivo


def _esperar(condicao, limite=3.0):
    fim = time.time() + limite
    while time.time() < fim and not condicao():
        time.sleep(0.01)
    return condicao()


def test_envia_amostras_enquanto_assinado_e_para_ao_cancelar():
    recebidos, reinicios = [], []
    vivo = aovivo.AoVivo(lambda: {"t": time.time()}, recebidos.append,
                         reiniciar=lambda: reinicios.append(1), intervalo=0.02)
    assert not vivo.ativo()
    vivo.assinar()
    vivo.assinar()  # renovar não abre uma segunda thread
    assert vivo.ativo()
    assert _esperar(lambda: len(recebidos) >= 3)
    assert reinicios == [1]

    vivo.cancelar()
    assert not vivo.ativo()
    time.sleep(0.06)
    parado = len(recebidos)
    time.sleep(0.1)
    assert len(recebidos) == parado


def test_vence_sozinho_sem_renovacao():
    """Cancelamento perdido ou painel fechado sem aviso: o celular para de medir."""
    agora = [0.0]
    recebidos = []
    vivo = aovivo.AoVivo(lambda: {}, recebidos.append, intervalo=0.02, validade=30,
                         relogio=lambda: agora[0])
    vivo.assinar()
    assert _esperar(lambda: recebidos)
    agora[0] = 31.0
    assert _esperar(lambda: not vivo.ativo())

    vivo.assinar()  # pode ser assinado de novo depois de vencer
    assert vivo.ativo()
    vivo.cancelar()


def test_erro_ao_medir_ou_enviar_nao_derruba_a_thread():
    chamadas = []

    def medir():
        chamadas.append(1)
        if len(chamadas) == 1:
            raise OSError("proc ilegível")
        return {"n": len(chamadas)}

    enviados = []

    def enviar(a):
        enviados.append(a)
        if len(enviados) == 1:
            raise RuntimeError("socket caiu")

    vivo = aovivo.AoVivo(medir, enviar, intervalo=0.02)
    vivo.assinar()
    assert _esperar(lambda: len(enviados) >= 2)
    vivo.cancelar()
