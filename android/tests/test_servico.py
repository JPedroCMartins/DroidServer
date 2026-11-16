import os
import threading
import time

import pytest

import servico


class _Proc:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


@pytest.fixture
def termux(monkeypatch, tmp_path):
    """PREFIX falso com um container 'w1' (layout novo do proot-distro)."""
    monkeypatch.setenv("PREFIX", str(tmp_path))
    raiz = tmp_path / "var/lib/proot-distro/containers/w1/rootfs"
    (raiz / "app").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def comandos(monkeypatch):
    """Registra os comandos executados; 'respostas' permite simular saídas."""
    class Registro(list):
        pass

    registro = Registro()
    respostas = {}

    def fake_run(cmd, **kw):
        registro.append(cmd)
        chave = " ".join(cmd[3:]) if cmd[:1] == ["supervisorctl"] else " ".join(cmd)
        return respostas.get(chave, _Proc())

    monkeypatch.setattr("subprocess.run", fake_run)
    registro.respostas = respostas
    return registro


def _sup(cmds):
    """Só os argumentos depois de `supervisorctl -c <conf>`."""
    return [c[3:] for c in cmds if c[:1] == ["supervisorctl"]]


# ---------- .conf ----------

def test_conf_gerado_e_lido_de_volta(termux):
    servico.gravar_conf("w1", isolado=False, autostart=False, autorestart=True)
    texto = open(servico.arquivo_conf("w1")).read()
    assert servico.CONF_VERSAO in texto
    assert "-- /bin/sh /app/.droidserver/lancador.sh" in texto and "--isolated" not in texto
    assert "stopasgroup=true" in texto and "stdout_logfile_maxbytes=1MB" in texto
    assert servico.ler_opcoes("w1") == {"isolado": False, "autostart": False, "autorestart": True, "atual": True}
    assert servico.ler_opcoes("nao_existe") is None


# ---------- run.sh ----------

def test_salvar_e_ler_script(termux):
    ok, _ = servico.salvar_script("w1", "#!/bin/sh\r\nexec python3 -m http.server 8080")
    assert ok
    caminho = termux / "var/lib/proot-distro/containers/w1/rootfs/app/run.sh"
    assert caminho.read_text() == "#!/bin/sh\nexec python3 -m http.server 8080\n"  # CRLF -> LF, \n final
    assert os.access(caminho, os.X_OK)
    assert servico.ler_script("w1") == caminho.read_text()


@pytest.mark.parametrize("conteudo,erro", [("x" * (64 * 1024 + 1), "64 KB"), ("a\0b", "nulos"), (None, "inválido")])
def test_salvar_script_recusa(termux, conteudo, erro):
    ok, msg = servico.salvar_script("w1", conteudo)
    assert not ok and erro in msg


def test_avisos_para_servico_em_segundo_plano():
    assert servico.avisos_script("cd /app\npython3 app.py &\n")
    assert servico.avisos_script("nohup python3 app.py")
    assert servico.avisos_script("cd /app && exec python3 app.py") == []
    assert servico.avisos_script("") == []


# ---------- migração ----------

def _conf_antigo(termux, alias="w1", isolado=True):
    conf = termux / "etc/supervisor/conf.d" / f"{alias}.conf"
    conf.parent.mkdir(parents=True, exist_ok=True)
    login = "proot-distro login " + ("--isolated " if isolado else "") + alias
    conf.write_text(f"[program:{alias}]\n            command=sh -c 'exec {login} -- /app/run_server.sh'\n"
                    "            autostart=true\n            autorestart=true\n")


def test_migra_run_server_personalizado_para_run_sh(termux, comandos):
    app = termux / "var/lib/proot-distro/containers/w1/rootfs/app"
    (app / "run_server.sh").write_text("#!/bin/sh\nexec python3 /app/app.py\n")
    _conf_antigo(termux)

    assert servico.migrar_todos(["w1"]) == ["w1"]
    assert (app / "run.sh").read_text() == "#!/bin/sh\nexec python3 /app/app.py\n"
    assert not (app / "run_server.sh").exists()
    assert (app / ".droidserver/lancador.sh").exists()
    assert servico.ler_opcoes("w1") == {"isolado": True, "autostart": True, "autorestart": True, "atual": True}
    assert ["reread"] in _sup(comandos) and ["update"] in _sup(comandos)
    # o serviço antigo é parado e as sessões encerradas ANTES do update
    ordem = [" ".join(c[3:]) if c[0] == "supervisorctl" else " ".join(c) for c in comandos]
    assert ordem.index("stop w1") < ordem.index("proot-distro kill w1") < ordem.index("update")


def test_migra_descarta_script_ocioso_e_nao_sobrescreve_run_sh(termux, comandos):
    app = termux / "var/lib/proot-distro/containers/w1/rootfs/app"
    (app / "run_server.sh").write_text("#!/bin/sh\necho oi\nwhile true; do sleep 30; done\n")
    _conf_antigo(termux, isolado=False)
    servico.migrar("w1")
    assert not (app / "run_server.sh").exists() and not (app / "run.sh").exists()
    assert servico.ler_opcoes("w1")["isolado"] is False

    # um worker já migrado não é tocado de novo
    comandos.clear()
    assert servico.migrar_todos(["w1"]) == []
    assert comandos == []


# ---------- estado ----------

def test_status_e_estado_dos_servicos(termux, comandos):
    comandos.respostas["status"] = _Proc(3, out=(
        "w1      RUNNING   pid 4321, uptime 1 day, 2:03:04\n"
        "w2      FATAL     Exited too quickly (process log may have details)\n"
        "unix:///x no such file\n"))
    st = servico.status_supervisor()
    assert st["w1"] == {"estado": "RUNNING", "pid": 4321, "uptime": "1 day, 2:03:04", "detalhe": ""}
    assert st["w2"]["estado"] == "FATAL" and "Exited too quickly" in st["w2"]["detalhe"]

    servico.gravar_conf("w1", autostart=False)
    servico.salvar_script("w1", "exec sleep 1")
    est = servico.estado_servicos(["w1"], st)["w1"]
    assert est["tem_script"] and est["gerenciado"] and est["autostart"] is False and est["pid"] == 4321


# ---------- comandos do painel ----------

def test_executar_valida(termux, comandos):
    assert servico.executar("../x", "iniciar")[0] is False
    assert servico.executar("w1", "apagar_tudo")[0] is False
    assert servico.executar("w9", "iniciar")[0] is False            # container inexistente
    assert servico.executar("w1", "iniciar")[0] is False            # sem serviço no supervisor
    ok, _, extra = servico.executar("w1", "exemplo")
    assert ok and "exec python3 -m http.server 8080" in extra["conteudo"]


def test_salvar_e_reiniciar(termux, comandos):
    servico.gravar_conf("w1")
    ok, msg, extra = servico.executar("w1", "salvar_script", {"conteudo": "python3 app.py &", "reiniciar": True})
    assert ok and "reiniciado" in msg
    assert extra["avisos"]  # aviso do '&'
    assert ["restart", "w1"] in _sup(comandos)
    ok, _, extra = servico.executar("w1", "ler_script")
    assert extra == {"conteudo": "python3 app.py &\n", "existe": True, "avisos": extra["avisos"]}


def test_configurar_so_rele_e_reiniciar_aplica(termux, comandos):
    servico.gravar_conf("w1")
    ok, _, extra = servico.executar("w1", "configurar", {"autostart": False})
    assert ok and extra == {"autostart": False, "autorestart": True}
    assert servico.ler_opcoes("w1")["autostart"] is False
    assert ["update"] not in _sup(comandos) and not any(c[:1] == ["update"] for c in _sup(comandos))

    # com o .conf alterado, reiniciar usa update (aplica) + start
    comandos.respostas["reread"] = _Proc(out="w1: changed\n")
    comandos.clear()
    assert servico.executar("w1", "reiniciar")[0]
    assert _sup(comandos) == [["reread"], ["update", "w1"], ["start", "w1"]]


@pytest.mark.parametrize("acao,esperado", [("parar", ["stop", "w1"]), ("iniciar", ["start", "w1"])])
def test_iniciar_e_parar(termux, comandos, acao, esperado):
    servico.gravar_conf("w1")
    ok, msg, _ = servico.executar("w1", acao)
    assert ok and esperado in _sup(comandos)


def test_erro_do_supervisor_vira_falha(termux, comandos):
    servico.gravar_conf("w1")
    comandos.respostas["start w1"] = _Proc(out="w1: ERROR (spawn error)")
    ok, msg, _ = servico.executar("w1", "iniciar")
    assert not ok and "spawn error" in msg


# ---------- logs ----------

def test_ultimas_linhas(tmp_path):
    arq = tmp_path / "log"
    arq.write_text("".join(f"linha {i}\n" for i in range(1000)))
    linhas, pos = servico.ultimas_linhas(str(arq), n=3, bloco=64)
    assert linhas == ["linha 997", "linha 998", "linha 999"] and pos == arq.stat().st_size
    assert servico.ultimas_linhas(str(tmp_path / "nada")) == ([], 0)


def test_logs_ao_vivo_envia_inicial_novas_e_trata_rotacao(termux):
    log_path = servico.arquivo_log("w1")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w") as f:
        f.write("antiga 1\nantiga 2\n")

    recebidos = []
    chegou = threading.Event()

    def enviar(alias, linhas, inicial):
        recebidos.append((alias, linhas, inicial))
        chegou.set()

    logs = servico.LogsAoVivo(enviar, intervalo=0.05)
    logs.assinar("w1")
    assert recebidos[0] == ("w1", ["antiga 1", "antiga 2"], True)

    def esperar(condicao):
        limite = time.time() + 3
        while time.time() < limite and not condicao():
            time.sleep(0.02)
        return condicao()

    with open(log_path, "a") as f:
        f.write("nova 1\nincomple")
    assert esperar(lambda: ("w1", ["nova 1"], False) in recebidos)
    with open(log_path, "a") as f:
        f.write("ta\n")
    assert esperar(lambda: ("w1", ["incompleta"], False) in recebidos)  # linha só sai quando completa

    with open(log_path, "w") as f:  # rotação: arquivo novo e menor
        f.write("depois da rotação\n")
    assert esperar(lambda: ("w1", ["depois da rotação"], False) in recebidos)

    assert logs.ativos() == {"w1"}
    logs.cancelar("w1")
    assert logs.ativos() == set()


@pytest.mark.parametrize("saida,falhou", [
    ("w1: ERROR (not running)\nw1: started", False),   # restart de um serviço FATAL
    ("w1: ERROR (already started)", False),
    ("w1: stopped\nw1: started", False),
    ("w1: ERROR (spawn error)", True),
    ("w1: ERROR (no such process)", True),
])
def test_interpretacao_da_saida_do_supervisorctl(saida, falhou):
    assert servico._falhou(saida) is falhou


def test_salvar_e_reiniciar_servico_que_estava_fatal(termux, comandos):
    servico.gravar_conf("w1")
    comandos.respostas["restart w1"] = _Proc(out="w1: ERROR (not running)\nw1: started\n")
    ok, msg, _ = servico.executar("w1", "salvar_script", {"conteudo": "exec sleep 9", "reiniciar": True})
    assert ok and msg == "run.sh salvo e serviço reiniciado."
