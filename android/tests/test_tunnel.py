import os
import stat

import pytest

import servico
import tunnel
from node import NodeAgent, WorkerManager
import node

TOKEN = "eyJhIjoiMTIzNDU2Nzg5MCIsInQiOiJhYmNkZWYtMTIzNCIsInMiOiJzZWdyZWRvIn0=" + "Zz9k"


class _Proc:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


@pytest.fixture
def termux(monkeypatch, tmp_path):
    monkeypatch.setenv("PREFIX", str(tmp_path / "usr"))
    monkeypatch.setenv("DROID_TUNNEL_ENV", str(tmp_path / "home/.config/droidserver/tunnel.env"))
    monkeypatch.setenv("DROID_REGISTRO_DIR", str(tmp_path / "registro"))
    monkeypatch.setattr(node, "PAREAMENTO_ARQUIVO", str(tmp_path / "pareamento.json"))
    for nome in ("DROID_HOST_IP", "DROID_HOST_PORT", "DROID_TOKEN"):
        monkeypatch.delenv(nome, raising=False)
    tunnel._versao_cache.clear()
    return tmp_path


@pytest.fixture
def comandos(monkeypatch):
    """Registra os comandos; o cloudflared 'existe' quando instalado=True."""
    class Registro(list):
        instalado = True
        status = ""

    registro = Registro()

    def fake_run(cmd, **kw):
        registro.append(cmd)
        if cmd[:3] == ["pkg", "install", "-y"]:
            registro.instalado = True
        if cmd[:1] == ["supervisorctl"] and cmd[3:4] == ["status"]:
            return _Proc(out=registro.status)
        return _Proc()

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(tunnel.shutil, "which",
                        lambda nome: "/usr/bin/cloudflared" if registro.instalado else None)
    return registro


def _sup(cmds):
    return [c[3:] for c in cmds if c[:1] == ["supervisorctl"]]


def test_token_valido():
    assert tunnel.token_valido(TOKEN)
    assert not tunnel.token_valido("curto")
    assert not tunnel.token_valido(TOKEN + "'; rm -rf ~")
    assert not tunnel.token_valido(None)


def test_configurar_grava_token_fora_do_conf(termux, comandos):
    ok, msg = tunnel.configurar(TOKEN)
    assert ok, msg
    conf = open(servico.arquivo_conf("tunnel")).read()
    assert TOKEN not in conf and TOKEN not in msg
    assert "exec cloudflared tunnel --no-autoupdate run" in conf
    assert f"stdout_logfile={servico.arquivo_log('tunnel')}" in conf
    env = tunnel.arquivo_env()
    assert stat.S_IMODE(os.stat(env).st_mode) == 0o600
    assert tunnel.ler_token() == TOKEN
    assert tunnel.token_fim() == "Zz9k"
    assert ["update", "tunnel"] in _sup(comandos) and ["start", "tunnel"] in _sup(comandos)
    assert not any(c[:1] == ["pkg"] for c in comandos)


def test_configurar_instala_quando_falta(termux, comandos):
    comandos.instalado = False
    ok, _ = tunnel.configurar(TOKEN)
    assert ok
    assert ["pkg", "install", "-y", "cloudflared"] in comandos


def test_configurar_falha_na_instalacao(termux, comandos, monkeypatch):
    comandos.instalado = False
    monkeypatch.setattr(tunnel, "instalar", lambda: (False, "sem rede"))
    ok, msg = tunnel.configurar(TOKEN)
    assert not ok and msg == "sem rede"
    assert not os.path.exists(tunnel.arquivo_env())


def test_trocar_token_reinicia_se_rodando(termux, comandos):
    tunnel.configurar(TOKEN)
    comandos.status = "tunnel   RUNNING   pid 42, uptime 0:01:00\n"
    comandos.clear()
    novo = "A" * 60
    ok, _ = tunnel.configurar(novo)
    assert ok and tunnel.ler_token() == novo
    assert ["restart", "tunnel"] in _sup(comandos)


def test_configurar_rejeita_token_invalido(termux, comandos):
    ok, _ = tunnel.configurar("x")
    assert not ok and comandos == []


def test_remover_limpa_tudo(termux, comandos):
    tunnel.configurar(TOKEN)
    log_ = servico.arquivo_log("tunnel")
    open(log_, "w").write("linha\n")
    ok, _ = tunnel.remover()
    assert ok
    for caminho in (servico.arquivo_conf("tunnel"), tunnel.arquivo_env(), log_):
        assert not os.path.exists(caminho)
    assert ["stop", "tunnel"] in _sup(comandos)


def test_estado_nao_expoe_token(termux, comandos):
    assert tunnel.estado({})["configurado"] is False
    tunnel.configurar(TOKEN)
    st = tunnel.estado({"tunnel": {"estado": "RUNNING", "pid": 7, "uptime": "0:00:10", "detalhe": ""}})
    assert st["configurado"] and st["estado"] == "RUNNING" and st["token_fim"] == "Zz9k"
    assert TOKEN not in repr(st)


def test_executar_tunnel_sem_rootfs(termux, comandos):
    tunnel.configurar(TOKEN)
    ok, msg, _ = servico.executar("tunnel", "iniciar")
    assert ok, msg
    assert servico.executar("tunnel", "ler_script")[0] is False
    assert servico.executar("tunnel", "salvar_script", {"conteudo": "x"})[0] is False


def test_executar_configurar_tunnel_mantem_comando(termux, comandos):
    tunnel.configurar(TOKEN)
    ok, _, extra = servico.executar("tunnel", "configurar", {"autostart": False})
    assert ok and extra["autostart"] is False
    conf = open(servico.arquivo_conf("tunnel")).read()
    assert "cloudflared tunnel" in conf and "proot-distro" not in conf
    assert "autostart=false" in conf


def test_worker_nao_pode_se_chamar_tunnel(termux, comandos):
    ok, msg = WorkerManager.criar("tunnel", "alpine")
    assert not ok and "reservado" in msg


def test_tarefa_configurar_tunnel_no_agente(termux, comandos, caplog):
    agente = NodeAgent()
    with caplog.at_level("INFO"):
        agente._executar_tarefa({"acao": "configurar_tunnel", "token": TOKEN})
    assert agente._resultados[-1]["ok"] is True
    assert agente._resultados[-1]["alias"] == "tunnel"
    assert TOKEN not in repr(agente._resultados) and TOKEN not in caplog.text

    agente._executar_tarefa({"acao": "remover_tunnel"})
    assert agente._resultados[-1]["ok"] is True
    assert not os.path.exists(tunnel.arquivo_env())


def test_sync_envia_estado_e_tarefa_sem_token(termux, comandos, monkeypatch):
    enviados = {}

    class Resposta:
        status_code = 200

        def json(self):
            return {"tarefas": []}

    def fake_post(url, json=None, timeout=None):
        enviados.update(json)
        return Resposta()

    monkeypatch.setattr("requests.post", fake_post)
    agente = NodeAgent()
    agente._tarefa_atual = {"acao": "configurar_tunnel", "token": TOKEN}
    agente._poll_once()
    assert "tunnel" in enviados and enviados["tunnel"]["instalado"] is True
    assert TOKEN not in repr(enviados)
    assert enviados["tarefa_atual"]["token"] == "…Zz9k"
