import os
import signal
import struct
import threading

import pytest
import requests
from requests.exceptions import ConnectionError

from node import Config, NodeAgent, TerminalManager, WorkerManager
import sysinfo
from sysinfo import SystemMonitor


# ---------- Config ----------

def test_config_usa_variaveis_de_ambiente(monkeypatch):
    monkeypatch.setenv("DROID_HOST_IP", "10.0.0.9")
    monkeypatch.setenv("DROID_HOST_PORT", "7070")
    monkeypatch.setenv("DROID_TOKEN", "abc")

    c = Config()
    assert c.host_ip == "10.0.0.9"
    assert c.port == 7070
    assert c.token == "abc"
    assert c.http_url == "http://10.0.0.9:7070/api/node_sync"
    assert c.ws_url == "http://10.0.0.9:7070"


def test_config_usa_padroes(monkeypatch):
    monkeypatch.delenv("DROID_HOST_IP", raising=False)
    monkeypatch.delenv("DROID_HOST_PORT", raising=False)
    monkeypatch.delenv("DROID_TOKEN", raising=False)

    c = Config()
    assert c.host_ip == "192.168.1.10"
    assert c.port == 5050
    assert c.token == ""


def test_config_aceita_override_direto():
    c = Config(host_ip="1.2.3.4", port=9999, token="x")
    assert c.host_ip == "1.2.3.4"
    assert c.port == 9999
    assert c.token == "x"


# ---------- WorkerManager ----------

def test_worker_criar_instala_e_escreve_conf(monkeypatch, tmp_path):
    comandos = []

    def fake_run(cmd, **kw):
        comandos.append(cmd)
        return None

    class FakePopen:
        instances = []

        def __init__(self, cmd, stdin=None):
            self.cmd = cmd
            self.stdin = stdin
            FakePopen.instances.append(self)

        def communicate(self, data, timeout=None):
            self.data = data
            return (None, None)

        @property
        def returncode(self):
            return 0

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("subprocess.Popen", FakePopen)
    monkeypatch.setenv("PREFIX", str(tmp_path))

    ok, msg = WorkerManager.criar("worker_bd", "alpine")
    assert ok is True

    assert any("proot-distro" in c and "install" in c and "worker_bd" in c for c in comandos)
    assert any("supervisorctl" in c and "reread" in c for c in comandos)

    conf = tmp_path / "etc" / "supervisor" / "conf.d" / "worker_bd.conf"
    assert conf.exists()
    conteudo = conf.read_text()
    assert "[program:worker_bd]" in conteudo
    assert "command=proot-distro login worker_bd -- /app/run_server.sh" in conteudo

    assert len(FakePopen.instances) == 1
    assert "worker_bd" in FakePopen.instances[0].cmd
    assert b"DroidServer" in FakePopen.instances[0].data
    assert b"sleep 30" in FakePopen.instances[0].data


def test_worker_criar_rejeita_alias_invalido(monkeypatch, tmp_path):
    monkeypatch.setenv("PREFIX", str(tmp_path))
    ok, msg = WorkerManager.criar("../etc/evil", "alpine")
    assert ok is False
    assert "inválido" in msg.lower()


def test_worker_criar_rejeita_container_existente(monkeypatch, tmp_path):
    rootfs = tmp_path / "var/lib/proot-distro/installed-rootfs"
    (rootfs / "worker_bd").mkdir(parents=True)
    monkeypatch.setenv("PREFIX", str(tmp_path))

    ok, msg = WorkerManager.criar("worker_bd", "alpine")
    assert ok is False
    assert "já existe" in msg.lower()


def test_worker_deletar_para_e_remove_conf(monkeypatch, tmp_path):
    comandos = []

    def fake_run(cmd, **kw):
        comandos.append(cmd)
        return None

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setenv("PREFIX", str(tmp_path))

    conf = tmp_path / "etc" / "supervisor" / "conf.d" / "worker_bd.conf"
    conf.parent.mkdir(parents=True)
    conf.write_text("[program:worker_bd]\n")
    rootfs = tmp_path / "var/lib/proot-distro/installed-rootfs/worker_bd"
    rootfs.mkdir(parents=True)

    ok, msg = WorkerManager.deletar("worker_bd")
    assert ok is True

    assert not conf.exists()
    assert any("supervisorctl" in c and "stop" in c and "worker_bd" in c for c in comandos)
    assert any("proot-distro" in c and "remove" in c and "worker_bd" in c for c in comandos)


def test_worker_deletar_ignora_falha_do_install(monkeypatch, tmp_path):
    monkeypatch.setattr("subprocess.run", lambda *a, **k: None)
    monkeypatch.setenv("PREFIX", str(tmp_path))
    ok, msg = WorkerManager.deletar("inexistente")
    # Não deve levantar exceção mesmo sem configuração/logs no sistema
    assert ok is True


def test_get_installed_workers_sem_pasta(monkeypatch, tmp_path):
    monkeypatch.setenv("PREFIX", str(tmp_path))
    assert WorkerManager.get_installed_workers() == []


def test_get_installed_workers_lista_rootfs(monkeypatch, tmp_path):
    rootfs = tmp_path / "var/lib/proot-distro/installed-rootfs"
    (rootfs / "alpine_bd").mkdir(parents=True)
    (rootfs / "web1").mkdir(parents=True)

    monkeypatch.setenv("PREFIX", str(tmp_path))
    assert sorted(WorkerManager.get_installed_workers()) == ["alpine_bd", "web1"]


# ---------- TerminalManager ----------

def test_iniciar_pty_pai_registra_fd(monkeypatch):
    monkeypatch.setattr("pty.fork", lambda: (1234, 9))
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)

    agente = NodeAgent()
    agente.terminal.iniciar_pty("w1")

    assert agente.terminal.ativos["w1"] == (9, 1234)


def test_iniciar_pty_filho_executa_proot(monkeypatch):
    executados = {}

    def fake_fork():
        return (0, 0)

    def fake_execvp(nome, args):
        executados["nome"] = nome
        executados["args"] = args
        raise SystemExit(0)

    monkeypatch.setattr("pty.fork", fake_fork)
    monkeypatch.setattr("os.execvp", fake_execvp)
    monkeypatch.setenv("TERM", "")

    agente = NodeAgent()
    with pytest.raises(SystemExit):
        agente.terminal.iniciar_pty("w1")

    assert executados["nome"] == "proot-distro"
    assert executados["args"] == ["proot-distro", "login", "w1"]
    assert os.environ.get("TERM") == "xterm-256color"


def test_iniciar_pty_nao_duplica(monkeypatch):
    monkeypatch.setattr("pty.fork", lambda: (1, 9))
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)

    agente = NodeAgent()
    agente.terminal.ativos["w1"] = (7, 1)
    agente.terminal.iniciar_pty("w1")

    assert agente.terminal.ativos["w1"] == (7, 1)  # mantém o original


def test_escrever_comando_escreve_no_pty(monkeypatch):
    escritas = []
    monkeypatch.setattr("os.write", lambda fd, data: escritas.append((fd, data)))

    agente = NodeAgent()
    agente.terminal.ativos["w1"] = (42, 1)
    agente.terminal.escrever_comando("w1", "ls\n")

    assert escritas == [(42, b"ls\n")]


def test_encerrar_sessao_mata_processo(monkeypatch):
    mortos = []
    escritas = []
    monkeypatch.setattr("os.kill", lambda pid, sig: mortos.append((pid, sig)))
    monkeypatch.setattr("os.write", lambda fd, data: escritas.append(data))

    agente = NodeAgent()
    agente.terminal.ativos["w1"] = (7, 999)
    agente.terminal.encerrar("w1")

    assert mortos == [(999, signal.SIGTERM)]
    assert "w1" not in agente.terminal.ativos


def test_redimensionar_pty(monkeypatch):
    ioctls = []

    def fake_ioctl(fd, req, arg):
        ioctls.append((fd, req, arg))

    monkeypatch.setattr("fcntl.ioctl", fake_ioctl)

    import termios

    agente = NodeAgent()
    agente.terminal.ativos["w1"] = (7, 1)
    agente.terminal.redimensionar("w1", 120, 30)

    assert len(ioctls) == 1
    assert ioctls[0][0] == 7
    assert ioctls[0][1] == termios.TIOCSWINSZ
    assert ioctls[0][2] == struct.pack("HHHH", 30, 120, 0, 0)


def test_redimensionar_sem_sessao_nao_falha():
    agente = NodeAgent()
    agente.terminal.redimensionar("w1", 80, 24)  # não deve levantar


# ---------- SystemMonitor (CPU / memória) ----------

def test_system_monitor_amostra_cpu_e_mem(monkeypatch, tmp_path):
    stat = tmp_path / "stat"
    # formato: cpu user nice system idle iowait irq softirq steal guest guest_nice
    # idle+iowait = 9500, total = 11000 -> delta vs prev (10000, 9000) => cpu 50%
    stat.write_text("cpu  100 100 300 9200 300 0 500 500 0 0\n")
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(
        "MemTotal:        8000000 kB\n"
        "MemFree:         2000000 kB\n"
        "MemAvailable:    4000000 kB\n"
    )
    monkeypatch.setattr(sysinfo, "STAT_FILE", str(stat))
    monkeypatch.setattr(sysinfo, "MEMINFO_FILE", str(meminfo))

    mon = SystemMonitor()
    mon._prev_cpu = (10000, 9000)

    amostra = mon.sample()
    # cpu = 100 * (d_total - d_idle) / d_total = 100 * (1000 - 500) / 1000
    assert amostra["cpu"] == 50.0
    # mem: total 8GB, available 4GB -> usado 4GB (50%)
    assert amostra["mem"]["total"] == 8000000 * 1024
    assert amostra["mem"]["percent"] == 50.0


def test_system_monitor_sem_arquivos_nao_falha(monkeypatch, tmp_path):
    monkeypatch.setattr(sysinfo, "STAT_FILE", str(tmp_path / "nao_existe"))
    monkeypatch.setattr(sysinfo, "MEMINFO_FILE", str(tmp_path / "nao_existe"))

    mon = SystemMonitor()
    mon._prev_cpu = (100, 90)

    amostra = mon.sample()
    assert amostra["cpu"] is None
    assert amostra["mem"] is None


def test_system_monitor_primeira_amostra_sem_delta(monkeypatch, tmp_path):
    stat = tmp_path / "stat"
    stat.write_text("cpu  500 300 9000 500 200 0 500 0 0 0\n")
    monkeypatch.setattr(sysinfo, "STAT_FILE", str(stat))

    mon = SystemMonitor()
    amostra = mon.sample()
    assert "cpu" in amostra  # cpu pode ser None, mas o formato deve existir


# ---------- NodeAgent ----------

def test_poll_once_retorna_tarefas(monkeypatch):
    class RespostaFake:
        status_code = 200

        def json(self):
            return {"status": "ok", "tarefas": [{"acao": "criar_worker", "alias": "w1"}]}

    chamadas = {}

    def fake_post(url, json=None, timeout=None):
        chamadas["url"] = url
        chamadas["payload"] = json
        return RespostaFake()

    monkeypatch.setattr("requests.post", fake_post)

    agente = NodeAgent()
    tarefas = agente._poll_once()

    assert tarefas == [{"acao": "criar_worker", "alias": "w1"}]
    assert chamadas["url"] == agente.config.http_url
    assert chamadas["payload"]["ip"] == agente.meu_ip
    assert "workers" in chamadas["payload"]


def test_poll_once_envia_token_quando_configurado(monkeypatch):
    class RespostaFake:
        status_code = 200

        def json(self):
            return {"status": "ok", "tarefas": []}

    payload = {}

    def fake_post(url, json=None, timeout=None):
        payload.update(json)
        return RespostaFake()

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setenv("DROID_TOKEN", "segredo")

    agente = NodeAgent()
    agente._poll_once()

    assert payload["token"] == "segredo"


def test_poll_once_inclui_cpu_e_mem(monkeypatch):
    class RespostaFake:
        status_code = 200

        def json(self):
            return {"status": "ok", "tarefas": []}

    payload = {}

    def fake_post(url, json=None, timeout=None):
        payload.update(json)
        return RespostaFake()

    monkeypatch.setattr("requests.post", fake_post)

    agente = NodeAgent()
    agente.monitor.sample = lambda: {"cpu": 12.5, "mem": {"total": 8, "usado": 4, "percent": 50.0}}
    agente._poll_once()

    assert payload["cpu"] == 12.5
    assert payload["mem"] == {"total": 8, "usado": 4, "percent": 50.0}


def test_poll_once_erro_de_rede_retorna_vazio(monkeypatch):
    def fake_post(*a, **k):
        raise ConnectionError("sem rede")

    monkeypatch.setattr("requests.post", fake_post)

    agente = NodeAgent()
    assert agente._poll_once() == []


def test_poll_once_status_nao_200_retorna_vazio(monkeypatch):
    class RespostaFake:
        status_code = 401

        def json(self):
            return {"erro": "Não autorizado"}

    monkeypatch.setattr("requests.post", lambda *a, **k: RespostaFake())

    agente = NodeAgent()
    assert agente._poll_once() == []


def test_executar_tarefa_criar_worker(monkeypatch):
    chamadas = {}

    def fake_criar(alias, imagem):
        chamadas["alias"] = alias
        chamadas["imagem"] = imagem
        return (True, f"Container '{alias}' criado")

    monkeypatch.setattr(WorkerManager, "criar", staticmethod(fake_criar))

    agente = NodeAgent()
    agente._executar_tarefa({"acao": "criar_worker", "alias": "w1", "imagem": "alpine"})

    assert chamadas == {"alias": "w1", "imagem": "alpine"}
    assert len(agente._resultados) == 1
    assert agente._resultados[0]["ok"] is True
    assert agente._resultados[0]["alias"] == "w1"


def test_executar_tarefa_deletar_worker(monkeypatch):
    chamadas = []

    def fake_deletar(alias):
        chamadas.append(alias)
        return (True, f"Container '{alias}' deletado")

    monkeypatch.setattr(WorkerManager, "deletar", staticmethod(fake_deletar))

    agente = NodeAgent()
    agente._executar_tarefa({"acao": "deletar_worker", "alias": "w1"})

    assert chamadas == ["w1"]
    assert agente._resultados[0]["ok"] is True


def test_executar_tarefa_falha_registra_resultado(monkeypatch):
    def fake_criar(alias, imagem):
        return (False, f"Falha ao instalar '{alias}'")

    monkeypatch.setattr(WorkerManager, "criar", staticmethod(fake_criar))

    agente = NodeAgent()
    agente._executar_tarefa({"acao": "criar_worker", "alias": "w1"})

    assert agente._resultados[0]["ok"] is False
    assert "Falha" in agente._resultados[0]["msg"]


def test_poll_once_envia_e_limpa_resultados(monkeypatch):
    class RespostaFake:
        status_code = 200

        def json(self):
            return {"status": "ok", "tarefas": []}

    payload = {}

    def fake_post(url, json=None, timeout=None):
        payload.update(json)
        return RespostaFake()

    monkeypatch.setattr("requests.post", fake_post)

    agente = NodeAgent()
    agente._resultados = [{"acao": "criar_worker", "alias": "w1", "ok": True, "msg": "ok", "ts": "12:00"}]
    agente._tarefa_atual = {"acao": "criar_worker", "alias": "w1"}

    agente._poll_once()

    assert payload["resultados"] == [{"acao": "criar_worker", "alias": "w1", "ok": True, "msg": "ok", "ts": "12:00"}]
    assert payload["tarefa_atual"]["alias"] == "w1"
    # após o envio com sucesso, a lista local é limpa
    assert agente._resultados == []


def test_poll_once_nao_limpa_resultados_se_falhar(monkeypatch):
    def fake_post(*a, **k):
        raise ConnectionError("sem rede")

    monkeypatch.setattr("requests.post", fake_post)

    agente = NodeAgent()
    agente._resultados = [{"acao": "criar_worker", "alias": "w1", "ok": True, "msg": "ok", "ts": "12:00"}]
    agente._poll_once()

    assert len(agente._resultados) == 1  # mantém para tentar de novo


def test_get_workers_status_parseia_saida(monkeypatch):
    class ProcFake:
        returncode = 0
        stdout = (
            "worker_bd                         RUNNING   pid 123, uptime 0:01:00\n"
            "web1                              FATAL     Exited too quickly\n"
        )

    monkeypatch.setattr("subprocess.run", lambda *a, **k: ProcFake())

    assert WorkerManager.get_workers_status() == {"worker_bd": "RUNNING", "web1": "FATAL"}


def test_get_workers_status_erro_retorna_vazio(monkeypatch):
    def falha(*a, **k):
        raise OSError("sem supervisor")

    monkeypatch.setattr("subprocess.run", falha)
    assert WorkerManager.get_workers_status() == {}


def test_executar_tarefa_desconhecida_nao_falha():
    agente = NodeAgent()
    agente._executar_tarefa({"acao": "apagar_tudo"})  # não deve levantar
    assert agente._resultados == []


def test_conectar_ws_retenta_apos_falha(monkeypatch):
    agente = NodeAgent()
    agente.sio.connected = False

    tentativas = [Exception("boom")]

    def fake_connect(url):
        if tentativas:
            raise tentativas.pop(0)

    monkeypatch.setattr(agente.sio, "connect", fake_connect)

    assert agente._conectar_ws() is False
    assert agente._conectar_ws() is True


def test_conectar_ws_ja_conectado_nao_refaz(monkeypatch):
    agente = NodeAgent()
    agente.sio.connected = True

    def fake_connect(url):
        raise AssertionError("não deveria reconectar")

    monkeypatch.setattr(agente.sio, "connect", fake_connect)

    assert agente._conectar_ws() is True
