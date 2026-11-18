import json
import logging
import os
import socket
import stat

import pytest

import banco
import servico
import tunnel
from node import NodeAgent, WorkerManager

SENHA = "s3nha-Gerada_pelo-Host123"


class _Proc:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


@pytest.fixture
def termux(monkeypatch, tmp_path):
    """PREFIX falso, pacote postgresql "instalado" e porta 5432 livre."""
    monkeypatch.setenv("PREFIX", str(tmp_path / "usr"))
    monkeypatch.setenv("DROID_BANCOS_DIR", str(tmp_path / "bancos"))
    monkeypatch.setattr(banco, "instalado", lambda: True)
    monkeypatch.setattr(banco, "versao", lambda: "18.7")
    monkeypatch.setattr(banco, "_porta_livre", lambda porta: True)
    return tmp_path


@pytest.fixture
def comandos(monkeypatch):
    """subprocess.run falso: o initdb cria o cluster e guarda a senha que leu."""
    class Registro(list):
        pass

    registro = Registro()
    registro.senhas = []
    registro.initdb_rc = 0

    registro.psql = []          # (argv, script do stdin, PGPASSWORD)
    registro.psql_falha = None  # trecho de SQL que faz o psql falhar

    def fake_run(cmd, **kw):
        registro.append(cmd)
        if cmd[:1] == ["psql"]:
            script = kw.get("input") or ""
            registro.psql.append((cmd, script, (kw.get("env") or {}).get("PGPASSWORD")))
            if registro.psql_falha and registro.psql_falha in script:
                return _Proc(3, err="ERROR: erro simulado")
            return _Proc()
        if cmd[:1] == ["initdb"]:
            dados = cmd[cmd.index("-D") + 1]
            with open(cmd[cmd.index("--pwfile") + 1]) as f:
                registro.senhas.append(f.read().strip())
            if registro.initdb_rc:
                return _Proc(registro.initdb_rc, err="initdb: erro simulado")
            os.makedirs(dados)
            for nome in ("postgresql.conf", "pg_hba.conf"):
                with open(os.path.join(dados, nome), "w") as f:
                    f.write("# padrão\n")
        return _Proc()

    monkeypatch.setattr("subprocess.run", fake_run)
    return registro


def _sup(cmds):
    return [c[3:] for c in cmds if c[:1] == ["supervisorctl"]]


# ---------- criar ----------

def test_criar_inicializa_configura_e_registra(termux, comandos):
    ok, msg = banco.criar("pg1", SENHA)
    assert ok, msg
    assert "5432" in msg

    initdb = next(c for c in comandos if c[:1] == ["initdb"])
    assert initdb[initdb.index("-U") + 1] == "droidserver"
    assert "--auth-host=scram-sha-256" in initdb and "--auth-local=scram-sha-256" in initdb
    # a senha vai por arquivo, nunca na linha de comando, e o arquivo é apagado
    assert SENHA not in " ".join(initdb)
    assert comandos.senhas == [SENHA]
    assert not os.path.exists(os.path.join(banco.diretorio("pg1"), ".senha"))

    conf = open(os.path.join(banco.dir_dados("pg1"), "postgresql.conf")).read()
    assert "listen_addresses = '*'" in conf and "port = 5432" in conf
    assert "shared_buffers = 16MB" in conf and "max_connections = 20" in conf
    hba = open(os.path.join(banco.dir_dados("pg1"), "pg_hba.conf")).read()
    assert "0.0.0.0/0    scram-sha-256" in hba

    info = json.load(open(banco.arquivo_info("pg1")))
    assert info == {**info, "tipo": "postgres", "porta": 5432, "usuario": "droidserver",
                    "banco": "postgres", "senha": SENHA, "versao": "18.7"}
    assert stat.S_IMODE(os.stat(banco.arquivo_info("pg1")).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(banco.diretorio("pg1")).st_mode) == 0o700

    sv = open(servico.arquivo_conf("pg1")).read()
    assert "[program:pg1]" in sv and servico.CONF_VERSAO in sv
    assert f'command=postgres -D "{banco.dir_dados("pg1")}"' in sv
    assert "stopsignal=INT" in sv and "droidserver_pg1.log" in sv
    assert _sup(comandos) == [["reread"], ["update", "pg1"]]
    assert banco.existe("pg1") and banco.listar() == ["pg1"]


def test_criar_segunda_instancia_usa_a_proxima_porta(termux, comandos):
    assert banco.criar("pg1", SENHA)[0]
    ok, msg = banco.criar("pg2", SENHA)
    assert ok and "5433" in msg
    assert banco.ler_info("pg2")["porta"] == 5433


def test_escolher_porta_pula_porta_em_uso(termux, monkeypatch):
    monkeypatch.setattr(banco, "_porta_livre", lambda porta: porta != 5432)
    assert banco.escolher_porta() == 5433


def test_porta_livre_detecta_porta_ocupada():
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    s.bind(("0.0.0.0", 0))
    s.listen()
    try:
        assert banco._porta_livre(s.getsockname()[1]) is False
    finally:
        s.close()


@pytest.mark.parametrize("alias,senha,erro", [
    ("../x", SENHA, "Alias inválido"),
    ("tunnel", SENHA, "reservado"),
    ("pg1", "curta", "Senha"),
    ("pg1", None, "Senha"),
    ("pg1", "tem espaço e é longa o bastante", "Senha"),
])
def test_criar_valida_entrada(termux, comandos, alias, senha, erro):
    ok, msg = banco.criar(alias, senha)
    assert not ok and erro in msg
    assert comandos == []


def test_criar_recusa_nome_de_container_existente(termux, comandos):
    (termux / "usr/var/lib/proot-distro/containers/web/rootfs").mkdir(parents=True)
    ok, msg = banco.criar("web", SENHA)
    assert not ok and "Já existe" in msg


def test_container_recusa_nome_de_banco_existente(termux, comandos):
    assert banco.criar("pg1", SENHA)[0]
    ok, msg = WorkerManager.criar("pg1", "alpine")
    assert not ok and "banco" in msg


def test_criar_falha_no_initdb_limpa_tudo(termux, comandos):
    comandos.initdb_rc = 1
    ok, msg = banco.criar("pg1", SENHA)
    assert not ok and "erro simulado" in msg
    assert not os.path.exists(banco.diretorio("pg1"))
    assert not os.path.exists(servico.arquivo_conf("pg1"))
    assert _sup(comandos) == []


def test_criar_instala_o_pacote_se_faltar(termux, comandos, monkeypatch):
    estado = {"instalado": False}
    monkeypatch.setattr(banco, "instalado", lambda: estado["instalado"])

    def instalar():
        estado["instalado"] = True
        return True, "ok"
    monkeypatch.setattr(banco, "instalar", instalar)
    assert banco.criar("pg1", SENHA)[0]


def test_criar_para_se_a_instalacao_falhar(termux, comandos, monkeypatch):
    monkeypatch.setattr(banco, "instalado", lambda: False)
    monkeypatch.setattr(banco, "instalar", lambda: (False, "Falha ao instalar o PostgreSQL: sem rede"))
    ok, msg = banco.criar("pg1", SENHA)
    assert not ok and "sem rede" in msg
    assert not banco.existe("pg1")


# ---------- remover ----------

def test_remover_apaga_dados_conf_e_logs(termux, comandos):
    assert banco.criar("pg1", SENHA)[0]
    log = servico.arquivo_log("pg1")
    os.makedirs(os.path.dirname(log), exist_ok=True)
    for caminho in (log, log + ".1"):
        open(caminho, "w").close()
    del comandos[:]

    ok, msg = banco.remover("pg1")
    assert ok, msg
    assert _sup(comandos)[0] == ["stop", "pg1"]
    assert not os.path.exists(banco.diretorio("pg1"))
    assert not os.path.exists(servico.arquivo_conf("pg1"))
    assert not os.path.exists(log) and not os.path.exists(log + ".1")
    assert banco.listar() == []


# ---------- painel ----------

def test_estado_servicos_de_banco_sem_senha(termux, comandos):
    assert banco.criar("pg1", SENHA)[0]
    sv = servico.estado_servicos(["pg1"], {"pg1": {"estado": "RUNNING", "pid": 42, "uptime": "0:01:00",
                                                   "detalhe": ""}})["pg1"]
    assert sv["tipo"] == "postgres" and sv["porta"] == 5432
    assert sv["banco"] == {"tipo": "postgres", "porta": 5432, "usuario": "droidserver",
                           "banco": "postgres", "versao": "18.7", "bancos": []}
    assert sv["tem_script"] is True and sv["gerenciado"] is True
    assert sv["distro"] == "PostgreSQL 18.7 (Termux)"
    assert SENHA not in json.dumps(sv)


def test_executar_credenciais_so_para_banco(termux, comandos):
    assert banco.criar("pg1", SENHA)[0]
    ok, _, extra = servico.executar("pg1", "credenciais")
    assert ok and extra == {"usuario": "droidserver", "senha": SENHA, "banco": "postgres", "porta": 5432}

    (termux / "usr/var/lib/proot-distro/containers/web/rootfs/app").mkdir(parents=True)
    ok, msg, extra = servico.executar("web", "credenciais")
    assert not ok and extra == {}


@pytest.mark.parametrize("acao", ["ler_script", "salvar_script", "exemplo"])
def test_executar_banco_nao_tem_run_sh(termux, comandos, acao):
    assert banco.criar("pg1", SENHA)[0]
    ok, msg, _ = servico.executar("pg1", acao, {"conteudo": "x"})
    assert not ok and "run.sh" in msg


def test_executar_configurar_banco_regrava_conf(termux, comandos):
    assert banco.criar("pg1", SENHA)[0]
    ok, _, extra = servico.executar("pg1", "configurar", {"autostart": False})
    assert ok and extra == {"autostart": False, "autorestart": True}
    conf = open(servico.arquivo_conf("pg1")).read()
    assert "autostart=false" in conf and "postgres -D" in conf and "stopsignal=INT" in conf


def test_comando_terminal_abre_psql_com_senha_no_ambiente(termux, comandos):
    assert banco.criar("pg1", SENHA)[0]
    argv, env = banco.comando_terminal("pg1")
    assert argv[:2] == ["sh", "-c"]
    assert "psql -h 127.0.0.1 -p 5432 -U droidserver postgres" in argv[2]
    assert SENHA not in " ".join(argv)
    assert env == {"PGPASSWORD": SENHA}


# ---------- agente ----------

def test_tarefa_criar_banco_e_deletar(termux, comandos):
    agente = NodeAgent()
    agente._executar_tarefa({"acao": "criar_worker", "tipo": "postgres", "alias": "pg1", "senha": SENHA})
    assert agente._resultados[-1]["ok"] is True
    assert "pg1" in agente._amostrar()["workers"]

    agente._executar_tarefa({"acao": "deletar_worker", "alias": "pg1"})
    assert agente._resultados[-1]["ok"] is True
    assert not banco.existe("pg1")


def test_sem_segredo_oculta_a_senha_nos_logs(caplog):
    tarefa = {"acao": "criar_worker", "tipo": "postgres", "alias": "pg1", "senha": SENHA}
    limpa = tunnel.sem_segredo(tarefa)
    assert limpa["senha"] == "…" + SENHA[-4:]
    assert tarefa["senha"] == SENHA  # não altera a original
    with caplog.at_level(logging.INFO):
        logging.getLogger("node").info("Tarefa recebida: %s", limpa)
    assert SENHA not in caplog.text


# ---------- vários bancos por instância ----------

@pytest.fixture
def instancia(termux, comandos, monkeypatch):
    assert banco.criar("pg1", SENHA)[0]
    monkeypatch.setattr(banco, "rodando", lambda alias: True)
    comandos.psql.clear()
    return comandos


def test_criar_banco_usa_psql_sem_segredo_no_argv(instancia):
    ok, msg = banco.criar_banco("pg1", "app1")
    assert ok, msg
    info = banco.ler_info("pg1")
    senha_app = info["bancos"]["app1"]["senha"]
    assert banco.senha_valida(senha_app) and senha_app != SENHA

    consulta, criacao = instancia.psql
    for argv, script, pgpass in instancia.psql:
        assert argv[:2] == ["psql", "-h"] and "ON_ERROR_STOP=1" in argv
        assert senha_app not in " ".join(argv) and SENHA not in " ".join(argv)
        assert pgpass == SENHA
    assert "\\set nome 'app1'" in consulta[1] and "pg_roles" in consulta[1]
    assert f"\\set senha '{senha_app}'" in criacao[1]
    assert 'CREATE ROLE :"nome" LOGIN PASSWORD :\'senha\'' in criacao[1]
    assert 'CREATE DATABASE :"nome" OWNER :"nome"' in criacao[1]
    assert "REVOKE CONNECT" in criacao[1]
    # o sync mostra os nomes, nunca as senhas
    publica = banco.info_publica("pg1")
    assert publica["bancos"] == ["app1"] and senha_app not in json.dumps(publica)


@pytest.mark.parametrize("nome", ["postgres", "droidserver", "template1", "App", "1app", "a-b",
                                  "x'; DROP TABLE y; --", "", None, "a" * 64])
def test_criar_banco_valida_nome(instancia, nome):
    ok, msg = banco.criar_banco("pg1", nome)
    assert not ok and "inválido" in msg
    assert instancia.psql == []


def test_criar_banco_exige_servico_rodando(instancia, monkeypatch):
    monkeypatch.setattr(banco, "rodando", lambda alias: False)
    ok, msg = banco.criar_banco("pg1", "app1")
    assert not ok and "Inicie" in msg and instancia.psql == []


def test_criar_banco_recusa_nome_ja_existente_no_postgres(instancia, monkeypatch):
    original = banco.subprocess.run

    def com_existente(cmd, **kw):
        if cmd[:1] == ["psql"]:
            instancia.psql.append((cmd, kw.get("input"), None))
            return _Proc(0, out="1\n")
        return original(cmd, **kw)

    monkeypatch.setattr("subprocess.run", com_existente)
    ok, msg = banco.criar_banco("pg1", "app1")
    assert not ok and "Já existe" in msg
    assert len(instancia.psql) == 1  # nada foi criado nem desfeito
    assert banco.ler_info("pg1")["bancos"] == {}


def test_criar_banco_desfaz_se_falhar(instancia):
    instancia.psql_falha = "CREATE DATABASE"
    ok, msg = banco.criar_banco("pg1", "app1")
    assert not ok and "erro simulado" in msg
    assert "DROP DATABASE IF EXISTS" in instancia.psql[-1][1]
    assert banco.ler_info("pg1")["bancos"] == {}


def test_apagar_banco(instancia):
    assert banco.criar_banco("pg1", "app1")[0]
    assert banco.criar_banco("pg1", "app2")[0]
    ok, msg = banco.apagar_banco("pg1", "app1")
    assert ok, msg
    assert 'DROP DATABASE IF EXISTS :"nome" WITH (FORCE)' in instancia.psql[-1][1]
    assert "\\set nome 'app1'" in instancia.psql[-1][1]
    assert banco.info_publica("pg1")["bancos"] == ["app2"]


def test_apagar_banco_so_os_do_painel(instancia):
    ok, msg = banco.apagar_banco("pg1", "outro")
    assert not ok and "psql" in msg and instancia.psql == []


def test_credenciais_por_banco_pela_acao(instancia):
    assert servico.executar("pg1", "criar_banco", {"nome": "app1"})[0]
    senha_app = banco.ler_info("pg1")["bancos"]["app1"]["senha"]
    ok, _, extra = servico.executar("pg1", "credenciais", {"banco": "app1"})
    assert ok and extra == {"usuario": "app1", "senha": senha_app, "banco": "app1", "porta": 5432}
    ok, _, extra = servico.executar("pg1", "credenciais", {})
    assert ok and extra["usuario"] == "droidserver" and extra["senha"] == SENHA
    ok, msg, extra = servico.executar("pg1", "credenciais", {"banco": "nao_existe"})
    assert not ok and extra == {}


def test_acao_criar_banco_nao_devolve_senha(instancia):
    ok, msg, extra = servico.executar("pg1", "criar_banco", {"nome": "app1"})
    senha_app = banco.ler_info("pg1")["bancos"]["app1"]["senha"]
    assert ok and extra == {"bancos": ["app1"]}
    assert senha_app not in msg


def test_acoes_de_banco_so_para_worker_de_banco(termux, comandos):
    (termux / "usr/var/lib/proot-distro/containers/web/rootfs/app").mkdir(parents=True)
    ok, msg, _ = servico.executar("web", "criar_banco", {"nome": "app1"})
    assert not ok


# ---------- versão ----------

def test_instalar_segura_o_pacote(termux, comandos, monkeypatch):
    estado = {"instalado": False}
    monkeypatch.setattr(banco, "instalado", lambda: estado["instalado"])
    original = banco.subprocess.run

    def pkg(cmd, **kw):
        if cmd[:2] == ["pkg", "install"]:
            estado["instalado"] = True
        return original(cmd, **kw)

    monkeypatch.setattr("subprocess.run", pkg)
    assert banco.criar("pg1", SENHA)[0]
    assert ["apt-mark", "hold", "postgresql"] in comandos


def test_criar_segura_pacote_ja_instalado(termux, comandos):
    assert banco.criar("pg1", SENHA)[0]
    assert ["apt-mark", "hold", "postgresql"] in comandos


def _pg_version(alias, major):
    with open(os.path.join(banco.dir_dados(alias), "PG_VERSION"), "w") as f:
        f.write(f"{major}\n")


def test_versao_compativel(termux, comandos):
    assert banco.criar("pg1", SENHA)[0]
    _pg_version("pg1", "18")
    assert not banco.incompativel("pg1")
    ext = banco.extras("pg1")
    assert ext["versao_dados"] == "18" and ext["incompativel"] is False
    assert ext["distro"] == "PostgreSQL 18.7 (Termux)"


def test_versao_incompativel_avisa_e_nao_inicia(termux, comandos, monkeypatch):
    assert banco.criar("pg1", SENHA)[0]
    _pg_version("pg1", "17")
    assert banco.incompativel("pg1")
    ext = banco.extras("pg1")
    assert ext["incompativel"] is True and "dados da 17" in ext["distro"]

    comandos.clear()
    for acao in ("iniciar", "reiniciar"):
        ok, msg, _ = servico.executar("pg1", acao)
        assert not ok and "17" in msg and "18.7" in msg
    assert _sup(comandos) == []  # nem tentou subir
    assert servico.executar("pg1", "parar")[0]

    monkeypatch.setattr(banco, "rodando", lambda alias: True)
    ok, msg = banco.criar_banco("pg1", "app1")
    assert not ok and "versão" in msg
