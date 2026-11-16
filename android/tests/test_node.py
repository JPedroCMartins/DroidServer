import os
import signal
import struct
import threading

import pytest
import requests
from requests.exceptions import ConnectionError

from node import Config, NodeAgent, TerminalManager, WorkerManager
import node
import sysinfo
from sysinfo import SystemMonitor


@pytest.fixture(autouse=True)
def _pareamento_isolado(monkeypatch, tmp_path_factory):
    """Nenhum teste lê ou grava o pareamento real (~/.config/droidserver)."""
    arquivo = tmp_path_factory.mktemp("pareamento") / "pareamento.json"
    monkeypatch.setattr(node, "PAREAMENTO_ARQUIVO", str(arquivo))
    for nome in ("DROID_HOST_IP", "DROID_HOST_PORT", "DROID_TOKEN"):
        monkeypatch.delenv(nome, raising=False)
    return arquivo


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
    assert c.host_ip == ""          # sem pareamento e sem env: aguarda o painel
    assert c.pareado is False
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

    class RunResult:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kw):
        comandos.append(cmd)
        return RunResult()

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setenv("PREFIX", str(tmp_path))

    ok, msg = WorkerManager.criar("worker_bd", "alpine")
    assert ok is True

    assert any("proot-distro" in c and "install" in c and "worker_bd" in c for c in comandos)
    assert any("supervisorctl" in c and "reread" in c for c in comandos)
    # limpeza de artefatos residuais antes do install
    assert any("supervisorctl" in c and "stop" in c and "worker_bd" in c for c in comandos)
    assert any("proot-distro" in c and "remove" in c and "worker_bd" in c for c in comandos)

    conf = tmp_path / "etc" / "supervisor" / "conf.d" / "worker_bd.conf"
    assert conf.exists()
    conteudo = conf.read_text()
    assert "[program:worker_bd]" in conteudo
    # isolado por padrão, com limites ulimit e exec para o supervisor controlar o proot
    assert "exec proot-distro login --isolated worker_bd -- /app/run_server.sh" in conteudo
    assert "ulimit -n" in conteudo and "ulimit -u" in conteudo
    # toda chamada ao supervisorctl aponta para o supervisord.conf do Termux
    sup = [c for c in comandos if c and c[0] == "supervisorctl"]
    assert sup and all(c[1:3] == ["-c", str(tmp_path / "etc" / "supervisord.conf")] for c in sup)

    # injeção do run_server.sh acontece via base64 (sem depender de stdin)
    import base64
    injetor = [c for c in comandos if "run_server.sh" in " ".join(c)]
    assert len(injetor) == 1
    cmd_str = " ".join(injetor[0])
    assert "base64" in cmd_str
    script_b64 = None
    for tok in cmd_str.split():
        try:
            dec = base64.b64decode(tok)
        except Exception:
            continue
        if b"DroidServer" in dec:
            script_b64 = dec
            break
    assert script_b64 is not None
    assert b"sleep 30" in script_b64


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


def test_worker_criar_remove_conf_antigo(monkeypatch, tmp_path):
    class RunResult:
        returncode = 0
        stdout = ""
        stderr = ""

    comandos = []
    monkeypatch.setattr("subprocess.run", lambda cmd, **kw: (comandos.append(cmd), RunResult())[1])
    monkeypatch.setenv("PREFIX", str(tmp_path))

    conf = tmp_path / "etc" / "supervisor" / "conf.d" / "worker_bd.conf"
    conf.parent.mkdir(parents=True)
    conf.write_text("[program:worker_bd] (fantasma)\n")

    ok, msg = WorkerManager.criar("worker_bd", "alpine")
    assert ok is True
    # o conf é reescrito no final; a limpeza do fantasma ocorreu via proot-distro remove
    assert any("proot-distro" in c and "remove" in c and "worker_bd" in c for c in comandos)
    conteudo = conf.read_text()
    assert "[program:worker_bd]" in conteudo and "proot-distro login --isolated worker_bd" in conteudo


def test_worker_criar_captura_erro_do_install(monkeypatch, tmp_path):
    class RunResult:
        def __init__(self, rc=0, out="", err=""):
            self.returncode = rc
            self.stdout = out
            self.stderr = err

    def fake_run(cmd, **kw):
        if "install" in cmd:
            return RunResult(1, "", "erro do proot-distro: [Errno 11] resource busy")
        return RunResult()

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setenv("PREFIX", str(tmp_path))

    ok, msg = WorkerManager.criar("worker_bd", "alpine")
    assert ok is False
    assert "erro do proot-distro" in msg


class _Proc:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def test_worker_deletar_para_e_remove_conf(monkeypatch, tmp_path):
    comandos = []

    def fake_run(cmd, **kw):
        comandos.append(cmd)
        return _Proc()

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


def test_redimensionar_sem_sessao_abre_pty(monkeypatch):
    """O resize enviado ao abrir a tela do terminal já inicia a sessão."""
    monkeypatch.setattr("pty.fork", lambda: (1234, 9))
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)
    ioctls = []
    monkeypatch.setattr("fcntl.ioctl", lambda fd, req, arg: ioctls.append(fd))

    agente = NodeAgent()
    agente.terminal.redimensionar("w1", 80, 24)

    assert agente.terminal.ativos["w1"] == (9, 1234)
    assert ioctls == [9]


def test_redimensionar_alias_invalido_nao_abre_pty(monkeypatch):
    def nao_chamar():
        raise AssertionError("não deveria abrir PTY")

    monkeypatch.setattr("pty.fork", nao_chamar)
    agente = NodeAgent()
    agente.terminal.redimensionar("../x", 80, 24)
    assert agente.terminal.ativos == {}


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
    # isola do ambiente: no Android o top real responderia (fallback)
    monkeypatch.setattr(sysinfo, "_cpu_via_top", lambda: None)

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


def test_system_monitor_linha_curta(monkeypatch, tmp_path):
    # alguns kernels só expõem user/nice/system/idle (4 colunas)
    stat = tmp_path / "stat"
    stat.write_text("cpu  1000 200 800 3000\n")
    monkeypatch.setattr(sysinfo, "STAT_FILE", str(stat))

    mon = SystemMonitor()
    mon._prev_cpu = (1000, 2000)
    amostra = mon.sample()
    # atual: total=5000, idle=3000 -> d_total=4000, d_idle=1000 => 75%
    assert amostra["cpu"] == 75.0


def test_cpu_via_top_fallback(monkeypatch):
    class ProcFake:
        returncode = 0
        stdout = (
            "Tasks: 8 total,   1 running\n"
            "800%cpu   100%user   0%nice   0%sys 700%idle   0%iow\n"
        )

    monkeypatch.setattr("subprocess.run", lambda *a, **k: ProcFake())
    # (800 - 700) / 800 = 12.5%
    assert sysinfo._cpu_via_top() == 12.5


def test_cpu_via_top_sem_dados_retorna_none(monkeypatch):
    """Android 16: top sem acesso a /proc/stat mostra tudo zerado e 100% ocioso."""
    class ProcFake:
        returncode = 0
        stdout = (
            "Tasks: 9 total,   1 running\n"
            "800%cpu   0%user   0%nice   0%sys 800%idle   0%iow   0%irq   0%sirq   0%host\n"
        )

    monkeypatch.setattr("subprocess.run", lambda *a, **k: ProcFake())
    assert sysinfo._cpu_via_top() is None


def test_cpu_via_top_falha_retorna_none(monkeypatch):
    def falha(*a, **k):
        raise OSError("sem top")

    monkeypatch.setattr("subprocess.run", falha)
    assert sysinfo._cpu_via_top() is None


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

    def fake_criar(alias, imagem, isolado=True):
        chamadas["alias"] = alias
        chamadas["imagem"] = imagem
        chamadas["isolado"] = isolado
        return (True, f"Container '{alias}' criado")

    monkeypatch.setattr(WorkerManager, "criar", staticmethod(fake_criar))

    agente = NodeAgent()
    agente._executar_tarefa({"acao": "criar_worker", "alias": "w1", "imagem": "alpine"})

    assert chamadas == {"alias": "w1", "imagem": "alpine", "isolado": True}
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
    def fake_criar(alias, imagem, isolado=True):
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
    agente.config = Config(host_ip="10.0.0.1")
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


# ---------- Regressões ----------

def test_executar_tarefa_repassa_isolado_falso(monkeypatch):
    chamadas = {}

    def fake_criar(alias, imagem, isolado=True):
        chamadas["isolado"] = isolado
        return (True, "ok")

    monkeypatch.setattr(WorkerManager, "criar", staticmethod(fake_criar))
    agente = NodeAgent()
    agente._executar_tarefa({"acao": "criar_worker", "alias": "w1", "imagem": "debian", "isolado": False})
    assert chamadas["isolado"] is False


def test_worker_criar_sem_isolamento(monkeypatch, tmp_path):
    class RunResult:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr("subprocess.run", lambda cmd, **kw: RunResult())
    monkeypatch.setenv("PREFIX", str(tmp_path))

    ok, _ = WorkerManager.criar("w1", "debian", isolado=False)
    assert ok is True
    conteudo = (tmp_path / "etc" / "supervisor" / "conf.d" / "w1.conf").read_text()
    assert "--isolated" not in conteudo
    assert "exec proot-distro login w1 -- /app/run_server.sh" in conteudo


def test_worker_criar_rejeita_imagem_nao_permitida(monkeypatch, tmp_path):
    monkeypatch.setenv("PREFIX", str(tmp_path))
    ok, msg = WorkerManager.criar("w1", "windows")
    assert ok is False
    assert "não suportada" in msg


def test_worker_deletar_usa_conf_do_supervisor(monkeypatch, tmp_path):
    comandos = []
    monkeypatch.setattr("subprocess.run", lambda cmd, **kw: (comandos.append(cmd), _Proc())[1])
    monkeypatch.setenv("PREFIX", str(tmp_path))

    WorkerManager.deletar("w1")

    sup = [c for c in comandos if c[0] == "supervisorctl"]
    assert sup and all(c[1:3] == ["-c", str(tmp_path / "etc" / "supervisord.conf")] for c in sup)


def test_poll_once_preserva_resultado_registrado_durante_o_post(monkeypatch):
    """Um resultado que chega enquanto o POST está em andamento não pode ser apagado."""
    agente = NodeAgent()
    agente._registrar_resultado("criar_worker", "w1", True, "w1 criado")

    class RespostaFake:
        status_code = 200

        def json(self):
            return {"status": "ok", "tarefas": []}

    def fake_post(url, json=None, timeout=None):
        # Simula a thread de tarefas terminando outra operação durante o envio
        agente._registrar_resultado("deletar_worker", "w2", True, "w2 deletado")
        assert [r["alias"] for r in json["resultados"]] == ["w1"]
        return RespostaFake()

    monkeypatch.setattr("requests.post", fake_post)
    agente._poll_once()

    assert [r["alias"] for r in agente._resultados] == ["w2"]


def test_ler_saida_fecha_fd_e_recolhe_processo(monkeypatch):
    fechados, recolhidos = [], []
    monkeypatch.setattr("select.select", lambda r, w, x: (r, [], []))
    monkeypatch.setattr("os.read", lambda fd, n: b"")  # EOF: a sessão terminou
    monkeypatch.setattr("os.close", lambda fd: fechados.append(fd))
    monkeypatch.setattr("os.waitpid", lambda pid, flags: (recolhidos.append(pid), (pid, 0))[1])

    agente = NodeAgent()
    agente.terminal.ativos["w1"] = (9, 4321)
    agente.terminal._ler_saida(9, "w1", 4321)

    assert fechados == [9]
    assert recolhidos == [4321]
    assert "w1" not in agente.terminal.ativos


def test_ler_saida_nao_remove_sessao_nova_do_mesmo_alias(monkeypatch):
    monkeypatch.setattr("select.select", lambda r, w, x: (r, [], []))
    monkeypatch.setattr("os.read", lambda fd, n: b"")
    monkeypatch.setattr("os.close", lambda fd: None)
    monkeypatch.setattr("os.waitpid", lambda pid, flags: (pid, 0))

    agente = NodeAgent()
    agente.terminal.ativos["w1"] = (11, 5555)  # sessão nova, aberta depois
    agente.terminal._ler_saida(9, "w1", 4321)  # a antiga terminando

    assert agente.terminal.ativos["w1"] == (11, 5555)


def test_finalizar_sessao_forca_kill_se_processo_nao_sai(monkeypatch):
    sinais = []
    chamadas_wait = []

    def fake_waitpid(pid, flags):
        chamadas_wait.append(flags)
        return (0, 0) if flags == os.WNOHANG else (pid, 0)

    monkeypatch.setattr("os.close", lambda fd: None)
    monkeypatch.setattr("os.waitpid", fake_waitpid)
    monkeypatch.setattr("os.kill", lambda pid, sig: sinais.append(sig))

    TerminalManager._finalizar_sessao(9, 4321, espera=0)

    assert sinais == [signal.SIGKILL]
    assert chamadas_wait[-1] == 0  # recolhe de forma bloqueante após o SIGKILL


def _container_existente(tmp_path, alias="w1"):
    (tmp_path / "var/lib/proot-distro/containers" / alias).mkdir(parents=True)


def test_deletar_encerra_sessoes_e_retenta_remove(monkeypatch, tmp_path):
    """O remove falha enquanto uma sessão segura o lock; o agente tenta de novo."""
    _container_existente(tmp_path)
    monkeypatch.setenv("PREFIX", str(tmp_path))
    monkeypatch.setattr("time.sleep", lambda s: None)
    comandos, removes = [], []

    def fake_run(cmd, **kw):
        comandos.append(cmd)
        if cmd[:2] == ["proot-distro", "remove"]:
            removes.append(cmd)
            if len(removes) == 1:
                return _Proc(1, err="\x1b[31mcontainer is locked\x1b[0m")
        return _Proc()

    monkeypatch.setattr("subprocess.run", fake_run)
    ok, msg = WorkerManager.deletar("w1")

    assert ok is True
    assert len(removes) == 2
    kill = comandos.index(["proot-distro", "kill", "w1"])
    assert kill < comandos.index(removes[0])  # sessões encerradas antes do remove


def test_deletar_reporta_erro_real_do_remove(monkeypatch, tmp_path):
    _container_existente(tmp_path)
    monkeypatch.setenv("PREFIX", str(tmp_path))
    monkeypatch.setattr("time.sleep", lambda s: None)

    def fake_run(cmd, **kw):
        if cmd[:2] == ["proot-distro", "remove"]:
            return _Proc(1, err="\x1b[31mError: container is in use\x1b[0m")
        return _Proc()

    monkeypatch.setattr("subprocess.run", fake_run)
    ok, msg = WorkerManager.deletar("w1")

    assert ok is False
    assert "container is in use" in msg and "\x1b" not in msg


# ---------- CPU dos processos (total e por worker) ----------

def _proc_falso(raiz, processos):
    """Cria um /proc falso: processos = {pid: (ppid, utime, stime, nome)}."""
    for pid, (ppid, ut, st, nome) in processos.items():
        d = raiz / str(pid)
        d.mkdir(parents=True, exist_ok=True)
        # campos após o nome: estado ppid pgrp sess tty tpgid flags minflt cminflt majflt cmajflt utime stime ...
        (d / "stat").write_text(f"{pid} ({nome}) S {ppid} 0 0 0 0 0 0 0 0 0 {ut} {st} 0 0 20 0 1 0\n")


def test_ler_processos_le_ppid_e_ticks_com_nome_com_espacos(tmp_path):
    _proc_falso(tmp_path, {10: (1, 5, 3, "python node.py"), 11: (10, 0, 0, "sh (x)")})
    (tmp_path / "self").mkdir()  # entradas não numéricas são ignoradas
    assert sysinfo.ler_processos(str(tmp_path)) == {10: (1, 8), 11: (10, 0)}


def test_descendentes_segue_a_arvore():
    procs = {1: (0, 0), 10: (1, 0), 11: (10, 0), 12: (11, 0), 20: (1, 0)}
    assert sysinfo.descendentes(procs, [10]) == {10, 11, 12}
    assert sysinfo.descendentes(procs, [99]) == set()


def test_process_cpu_monitor_total_e_por_worker(monkeypatch, tmp_path):
    monkeypatch.setattr(sysinfo, "CLK_TCK", 100)
    # agente (100), worker w1: supervisor sh (200) -> proot (201); worker w2 (300)
    _proc_falso(tmp_path, {100: (1, 0, 0, "python"), 200: (1, 0, 0, "sh"),
                           201: (200, 0, 0, "proot"), 300: (1, 0, 0, "proot")})
    relogio = iter([0.0, 10.0])
    mon = sysinfo.ProcessCPUMonitor(proc_dir=str(tmp_path), ncpu=4, relogio=lambda: next(relogio))

    # Em 10 s: agente 1 s de CPU, w1 (proot) 20 s, w2 nada; processo novo 400 em w1 com 2 s
    _proc_falso(tmp_path, {100: (1, 60, 40, "python"), 200: (1, 0, 0, "sh"),
                           201: (200, 1500, 500, "proot"), 300: (1, 0, 0, "proot"),
                           400: (201, 150, 50, "app")})
    r = mon.sample({"w1": [200], "w2": [300]})

    # total = (1 + 20 + 2) s / 10 s / 4 núcleos = 57,5% do aparelho
    assert r["total"] == 57.5
    assert r["grupos"] == {"w1": 55.0, "w2": 0.0}


def test_process_cpu_monitor_sem_proc_nao_falha(tmp_path):
    mon = sysinfo.ProcessCPUMonitor(proc_dir=str(tmp_path / "nada"), ncpu=8)
    assert mon.sample({"w1": [1]}) == {"total": 0.0, "grupos": {"w1": 0.0}}


def test_get_workers_status_le_saida_mesmo_com_codigo_de_erro(monkeypatch):
    """supervisorctl sai com 3 quando algum programa não está RUNNING."""
    class ProcFake:
        returncode = 3
        stdout = (
            "api       RUNNING   pid 4321, uptime 0:05:00\n"
            "quebrado  FATAL     Exited too quickly (process log may have details)\n"
        )

    monkeypatch.setattr("subprocess.run", lambda *a, **k: ProcFake())
    status, pids = WorkerManager.get_workers_status_e_pids()
    assert status == {"api": "RUNNING", "quebrado": "FATAL"}
    assert pids == {"api": 4321}
    assert WorkerManager.get_workers_status() == status


def test_poll_once_envia_cpu_dos_workers_incluindo_terminal(monkeypatch):
    payload = {}

    class RespostaFake:
        status_code = 200

        def json(self):
            return {"tarefas": []}

    monkeypatch.setattr("requests.post", lambda url, json=None, timeout=None: (payload.update(json), RespostaFake())[1])
    monkeypatch.setattr(WorkerManager, "get_workers_status_e_pids",
                        staticmethod(lambda: ({"w1": "RUNNING"}, {"w1": 200})))
    monkeypatch.setattr(WorkerManager, "get_installed_workers", staticmethod(lambda: ["w1"]))

    agente = NodeAgent()
    agente.terminal.ativos["w1"] = (9, 555)  # sessão de terminal aberta no w1
    grupos_recebidos = {}

    def fake_sample(grupos=None):
        grupos_recebidos.update(grupos)
        return {"total": 12.5, "grupos": {"w1": 10.0}}

    monkeypatch.setattr(agente.cpu_processos, "sample", fake_sample)
    agente._poll_once()

    assert grupos_recebidos == {"w1": [200, 555]}
    assert payload["cpu_termux"] == 12.5
    assert payload["cpu_workers"] == {"w1": 10.0}
    assert payload["worker_status"] == {"w1": "RUNNING"}


# ---------- Ordem da criação ----------

def test_criar_prepara_o_script_antes_de_registrar_o_servico(monkeypatch, tmp_path):
    """O /app/run_server.sh precisa existir antes de o Supervisor subir o serviço."""
    conf = tmp_path / "etc" / "supervisor" / "conf.d" / "w1.conf"
    comandos = []
    monkeypatch.setattr("subprocess.run", lambda cmd, **kw: (comandos.append((cmd, conf.exists())), _Proc())[1])
    monkeypatch.setenv("PREFIX", str(tmp_path))

    ok, _ = WorkerManager.criar("w1", "alpine")

    assert ok is True
    script = next(existia for c, existia in comandos if "run_server.sh" in " ".join(c))
    update = [existia for c, existia in comandos if c[0] == "supervisorctl" and "update" in c]
    assert script is False      # .conf ainda não existia quando o script foi criado
    assert update[-1] is True   # registro no supervisor só depois


def test_criar_rejeita_archlinux(monkeypatch, tmp_path):
    monkeypatch.setenv("PREFIX", str(tmp_path))
    ok, msg = WorkerManager.criar("w1", "archlinux")
    assert ok is False and "não suportada" in msg


# ---------- Pareamento pelo painel ----------

TOKEN = "ab" * 24


def test_config_prefere_pareamento_ao_env(monkeypatch, _pareamento_isolado):
    monkeypatch.setenv("DROID_HOST_IP", "10.9.9.9")
    node.salvar_pareamento({"host_ip": "192.168.1.10", "host_port": 5050, "token": TOKEN})
    c = Config()
    assert (c.host_ip, c.port, c.token) == ("192.168.1.10", 5050, TOKEN)
    assert oct(os.stat(_pareamento_isolado).st_mode & 0o777) == "0o600"


def test_descoberta_info_identifica_o_node(monkeypatch):
    monkeypatch.setattr(node, "_getprop", lambda nome: {"ro.product.manufacturer": "Xiaomi",
                                                       "ro.product.model": "2311DRK48G",
                                                       "ro.build.version.release": "16"}[nome])
    agente = NodeAgent()
    status, corpo = node.Descoberta(agente).info()
    assert status == 200 and corpo["droidserver"] is True
    assert corpo["modelo"] == "Xiaomi 2311DRK48G" and corpo["android"] == "16"
    assert corpo["pareado"] is False and corpo["host"] is None


def test_parear_usa_o_ip_de_quem_pediu_e_recarrega(monkeypatch):
    agente = NodeAgent()
    status, corpo = node.Descoberta(agente).parear("192.168.1.10", {"host_port": 5050, "token": TOKEN})
    assert status == 200 and corpo["ok"] is True
    assert agente.config.host_ip == "192.168.1.10" and agente.config.token == TOKEN
    assert node.ler_pareamento()["host_ip"] == "192.168.1.10"


def test_parear_recusa_outro_host_quando_ja_pareado():
    agente = NodeAgent()
    d = node.Descoberta(agente)
    d.parear("192.168.1.10", {"host_port": 5050, "token": TOKEN})
    status, corpo = d.parear("192.168.1.66", {"host_port": 5050, "token": "cd" * 24})
    assert status == 409 and "192.168.1.10" in corpo["erro"]
    assert agente.config.host_ip == "192.168.1.10"
    # o mesmo host pode parear de novo (ex.: depois de remover e adicionar)
    assert d.parear("192.168.1.10", {"host_port": 5050, "token": "cd" * 24})[0] == 200
    assert agente.config.token == "cd" * 24


@pytest.mark.parametrize("dados", [{"token": "curto"}, {"token": "zz" * 20}, {"token": TOKEN, "host_port": 0},
                                   {"token": TOKEN, "host_port": "x"}])
def test_parear_valida_token_e_porta(dados):
    agente = NodeAgent()
    assert node.Descoberta(agente).parear("192.168.1.10", dados)[0] == 400
    assert agente.config.pareado is False


def test_desparear_so_pelo_host_com_token_e_ignora_env(monkeypatch):
    monkeypatch.setenv("DROID_HOST_IP", "10.9.9.9")  # modo antigo não pode "ressuscitar"
    agente = NodeAgent()
    d = node.Descoberta(agente)
    d.parear("192.168.1.10", {"host_port": 5050, "token": TOKEN})

    assert d.desparear("192.168.1.66", {"token": TOKEN})[0] == 403
    assert d.desparear("192.168.1.10", {"token": "00" * 24})[0] == 403
    assert d.desparear("192.168.1.10", {"token": TOKEN})[0] == 200
    assert agente.config.pareado is False
    assert node.ler_pareamento() is None


def test_loop_nao_sincroniza_sem_pareamento(monkeypatch):
    agente = NodeAgent()
    chamadas = []
    monkeypatch.setattr(agente, "_poll_once", lambda: chamadas.append(1) or [])

    def parar(_):
        raise SystemExit

    monkeypatch.setattr(node.time, "sleep", parar)
    with pytest.raises(SystemExit):
        agente._loop()
    assert chamadas == []


def test_servidor_de_descoberta_responde_por_http(monkeypatch):
    agente = NodeAgent()
    monkeypatch.setattr(node, "_getprop", lambda nome: "")
    servidor = node.iniciar_servidor_descoberta(node.Descoberta(agente), porta=0)
    try:
        url = f"http://127.0.0.1:{servidor.server_address[1]}"
        assert requests.get(url + "/droidserver", timeout=3).json()["droidserver"] is True
        r = requests.post(url + "/parear", json={"host_port": 5050, "token": TOKEN}, timeout=3)
        assert r.status_code == 200 and agente.config.host_ip == "127.0.0.1"
        assert requests.post(url + "/parear", data=b"[1,2]", timeout=3).status_code == 400
    finally:
        servidor.shutdown()


def test_parear_substitui_configuracao_antiga_por_env(monkeypatch):
    """Node configurado à mão (DROID_HOST_IP, sem token) aceita o pareamento do painel."""
    monkeypatch.setenv("DROID_HOST_IP", "10.9.9.9")
    agente = NodeAgent()
    assert agente.config.origem == "env"
    status, _ = node.Descoberta(agente).parear("192.168.1.10", {"host_port": 5050, "token": TOKEN})
    assert status == 200
    assert (agente.config.origem, agente.config.host_ip) == ("pareamento", "192.168.1.10")


def test_info_nao_mostra_configuracao_antiga_como_pareada(monkeypatch):
    monkeypatch.setenv("DROID_HOST_IP", "192.168.1.10")
    monkeypatch.setattr(node, "_getprop", lambda nome: "")
    agente = NodeAgent()
    _, corpo = node.Descoberta(agente).info()
    assert corpo["pareado"] is False and corpo["host"] is None
    node.Descoberta(agente).parear("192.168.1.10", {"host_port": 5050, "token": TOKEN})
    _, corpo = node.Descoberta(agente).info()
    assert corpo["pareado"] is True and corpo["host"] == "192.168.1.10:5050"
