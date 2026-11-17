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
    assert ["reread"] in _sup(comandos) and ["update", "w1"] in _sup(comandos)
    # o serviço antigo é parado e as sessões encerradas ANTES do update
    ordem = [" ".join(c[3:]) if c[0] == "supervisorctl" else " ".join(c) for c in comandos]
    assert ordem.index("stop w1") < ordem.index("proot-distro kill w1") < ordem.index("update w1")


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


# ---------- revisão: shebang, links simbólicos, ulimit ----------

def _rodar_lancador(tmp_path, script, modo):
    """Executa o lançador de verdade, com /app trocado por uma pasta temporária."""
    import subprocess
    app = tmp_path / "app"
    app.mkdir(exist_ok=True)
    (app / "run.sh").write_text(script)
    os.chmod(app / "run.sh", modo)
    lancador = servico.LANCADOR.replace("/app", str(app))
    return subprocess.run(["sh", "-c", lancador], capture_output=True, text=True, timeout=10).stdout


def test_lancador_respeita_o_shebang(tmp_path):
    py = "#!/usr/bin/env python3\nprint('via python', 2 ** 10)\n"
    assert "via python 1024" in _rodar_lancador(tmp_path, py, 0o755)
    # sem permissão de execução (criado à mão no terminal): cai no sh
    assert "via sh" in _rodar_lancador(tmp_path, "echo via sh\n", 0o644)
    assert "via sh" in _rodar_lancador(tmp_path, "echo via sh\n", 0o755)


def test_run_sh_link_simbolico_nao_e_seguido(termux, tmp_path):
    segredo = tmp_path / "pareamento.json"
    segredo.write_text('{"token": "segredo"}')
    app = termux / "var/lib/proot-distro/containers/w1/rootfs/app"
    os.symlink(segredo, app / "run.sh")
    assert servico.ler_script("w1") is None
    ok, msg = servico.salvar_script("w1", "echo oi")
    assert not ok and "link" in msg
    assert segredo.read_text() == '{"token": "segredo"}'

    # /app inteiro apontando para fora do container
    os.remove(app / "run.sh")
    os.rmdir(app)
    os.symlink(tmp_path, app)
    assert servico.ler_script("w1") is None
    assert servico.salvar_script("w1", "echo oi")[0] is False


def test_configurar_mantem_os_limites_personalizados(termux, comandos, monkeypatch):
    monkeypatch.setattr(servico, "ULIMIT_NOFILE", 777)
    servico.gravar_conf("w1")
    servico.executar("w1", "configurar", {"autostart": False})
    texto = open(servico.arquivo_conf("w1")).read()
    assert "ulimit -n 777" in texto


def test_migrar_todos_atualiza_lancador_antigo(termux, comandos):
    servico.gravar_conf("w1")
    lancador = termux / "var/lib/proot-distro/containers/w1/rootfs/app/.droidserver/lancador.sh"
    lancador.parent.mkdir(parents=True)
    lancador.write_text("#!/bin/sh\nexec sh /app/run.sh\n")  # versão anterior
    assert servico.migrar_todos(["w1"]) == []                  # .conf já atual: nada a migrar
    assert lancador.read_text() == servico.LANCADOR


# ---------- Fase 2B: visão geral do serviço ----------

@pytest.mark.parametrize("cab,porta", [
    ("#!/bin/sh\n# droidserver: porta=8080\nexec x", 8080),
    ("# droidserver: tipo=api porta=3000", 3000),
    ("#   DroidServer:  porta = 5000", 5000),
    ("exec x", None), ("# droidserver: porta=abc", None),
    ("# droidserver: porta=0", None), ("# droidserver: porta=70000", None), (None, None),
])
def test_ler_metadados_porta(cab, porta):
    assert servico.ler_metadados(cab)["porta"] == porta


def test_estado_traz_porta_distro_e_salvamento(termux, comandos):
    raiz = termux / "var/lib/proot-distro/containers/w1/rootfs"
    (raiz / "etc").mkdir()
    (raiz / "etc/os-release").write_text('NAME="Alpine"\nPRETTY_NAME="Alpine Linux v3.24"\n')
    servico.gravar_conf("w1")
    servico.salvar_script("w1", "# droidserver: porta=8080\nexec sleep 9")
    est = servico.estado_servicos(["w1"], {})["w1"]
    assert est["porta"] == 8080 and est["distro"] == "Alpine Linux v3.24"
    assert abs(est["script_salvo_em"] - time.time()) < 5


def test_exemplo_declara_a_porta():
    assert servico.ler_metadados(servico.EXEMPLO)["porta"] == 8080


LOG_SUP = """2026-11-15 23:59:01,1 WARN exited: w1 (exit status 1; not expected)
2026-11-16 18:07:45,172 WARN exited: w1 (exit status 127; not expected)
2026-11-16 18:07:50,994 INFO spawned: 'w1' with pid 24542
2026-11-16 18:08:00,000 WARN exited: w12 (exit status 1; not expected)
2026-11-16 18:09:00,000 INFO exited: w1 (exit status 0; expected)
2026-11-16 18:10:00,000 INFO stopped: w1 (terminated by SIGTERM)
"""


def test_falhas_do_dia(termux):
    conf = termux / "etc/supervisord.conf"
    conf.parent.mkdir(parents=True, exist_ok=True)
    conf.write_text(f"[supervisord]\nlogfile={termux}/var/log/supervisor/supervisord.log\n")
    log = termux / "var/log/supervisor/supervisord.log"
    log.parent.mkdir(parents=True)
    log.write_text(LOG_SUP)
    r = servico.falhas_do_dia(["w1", "w12", "w9"], hoje="2026-11-16")
    assert r["w1"] == {"falhas_hoje": 1, "ultima_falha":
                       {"quando": "18:07:45", "codigo": 127, "motivo": "comando não encontrado"}}
    assert r["w12"]["falhas_hoje"] == 1 and r["w9"] == {"falhas_hoje": 0, "ultima_falha": None}


def test_falhas_sem_log(termux):
    assert servico.falhas_do_dia(["w1"])["w1"] == {"falhas_hoje": 0, "ultima_falha": None}


def test_disco_calcula_em_segundo_plano(termux, monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        time.sleep(0.2)
        return _Proc(0, out="51200\t/x\n")

    monkeypatch.setattr("subprocess.run", fake_run)
    agora = [1000.0]
    d = servico.DiscoCache(validade=600, relogio=lambda: agora[0])
    assert d.mb("w1") is None                      # não bloqueia na 1ª consulta
    for _ in range(50):
        if d.mb("w1") is not None:
            break
        time.sleep(0.02)
    assert d.mb("w1") == 50.0 and len(calls) == 1  # 51200 kB -> 50 MB, um du só
    agora[0] += 601
    d.mb("w1")
    time.sleep(0.3)
    assert len(calls) == 2                          # venceu: recalcula
