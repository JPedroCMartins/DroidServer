import json
import os

import requests

import registro
from registro import Registro


def test_grava_e_le_amostras_em_ordem(tmp_path):
    r = Registro(str(tmp_path / "metricas.jsonl"))
    r.gravar({"t": 10.0, "cpu_termux": 1.0})
    r.gravar({"t": 20.0, "cpu_termux": 2.0})
    assert [a["cpu_termux"] for a in r.ler()] == [1.0, 2.0]


def test_grava_carimbo_quando_falta(tmp_path, monkeypatch):
    monkeypatch.setattr(registro.time, "time", lambda: 123.456)
    r = Registro(str(tmp_path / "m.jsonl"))
    r.gravar({"x": 1})
    assert r.ler() == [{"t": 123.5, "x": 1}]


def test_le_por_intervalo_de_tempo(tmp_path):
    r = Registro(str(tmp_path / "m.jsonl"))
    for t in (10, 20, 30, 40):
        r.gravar({"t": float(t)})
    assert [a["t"] for a in r.ler(desde=20, ate=30)] == [20.0, 30.0]


def test_rotacao_preserva_as_amostras_antigas_em_ordem(tmp_path):
    caminho = tmp_path / "m.jsonl"
    r = Registro(str(caminho), max_bytes=60, backups=5)
    for t in range(10):
        r.gravar({"t": float(t), "pad": "xxxxxxxxxx"})
    assert os.path.exists(f"{caminho}.1")
    assert [a["t"] for a in r.ler()] == [float(t) for t in range(10)]


def test_rotacao_descarta_alem_do_limite_de_backups(tmp_path):
    caminho = tmp_path / "m.jsonl"
    r = Registro(str(caminho), max_bytes=40, backups=2)
    for t in range(20):
        r.gravar({"t": float(t), "pad": "xxxxxxxxxx"})
    assert not os.path.exists(f"{caminho}.3")
    lidas = [a["t"] for a in r.ler()]
    assert lidas == sorted(lidas) and lidas[-1] == 19.0 and lidas[0] > 0


def test_linha_corrompida_e_ignorada(tmp_path):
    caminho = tmp_path / "m.jsonl"
    caminho.write_text('{"t": 1.0}\n{"t": 2.0, "x"\n\0\0\0\n{"t": 3.0}\n')
    assert [a["t"] for a in Registro(str(caminho)).ler()] == [1.0, 3.0]


def test_erro_de_disco_nao_propaga(tmp_path):
    bloqueio = tmp_path / "arquivo"
    bloqueio.write_text("")
    r = Registro(str(bloqueio / "sub" / "m.jsonl"))  # pai é um arquivo: não dá para criar
    r.gravar({"t": 1.0})  # não pode levantar exceção
    assert r.ler() == []


def test_arquivo_padrao_respeita_variavel(monkeypatch, tmp_path):
    monkeypatch.setenv("DROID_REGISTRO_DIR", str(tmp_path))
    assert registro.arquivo_padrao() == os.path.join(str(tmp_path), "metricas.jsonl")


def test_historico_resumido_para_o_painel(tmp_path):
    r = Registro(str(tmp_path / "m.jsonl"))
    r.gravar({"t": 100.0, "cpu_termux": 2.5, "ram_pct": 50.0, "servicos": {}})
    r.gravar({"t": 110.0, "cpu_termux": None, "ram_pct": 51.0})
    assert r.historico(desde=0) == [{"t": 100.0, "cpu": 2.5, "ram": 50.0},
                                    {"t": 110.0, "cpu": None, "ram": 51.0}]


def test_historico_limita_quantidade(tmp_path):
    r = Registro(str(tmp_path / "m.jsonl"))
    for t in range(10):
        r.gravar({"t": float(t)})
    assert [a["t"] for a in r.historico(desde=0, maximo=3)] == [7.0, 8.0, 9.0]


# ---------- verificação HTTP local ----------

class _Resp:
    def __init__(self, status):
        self.status_code = status


def test_checar_http_ok(monkeypatch):
    chamadas = {}

    def fake_get(url, timeout=None, allow_redirects=None):
        chamadas["url"] = url
        return _Resp(200)

    monkeypatch.setattr(registro.requests, "get", fake_get)
    res = registro.checar_http(8080)
    assert chamadas["url"] == "http://127.0.0.1:8080/"
    assert res["http_ok"] is True and res["http_status"] == 200 and res["http_ms"] >= 0 and res["erro"] == ""


def test_checar_http_status_de_erro(monkeypatch):
    monkeypatch.setattr(registro.requests, "get", lambda *a, **k: _Resp(502))
    res = registro.checar_http(8080)
    assert res["http_ok"] is False and res["http_status"] == 502


def test_checar_http_sem_resposta(monkeypatch):
    def falha(*a, **k):
        raise requests.exceptions.ConnectionError("recusado")

    monkeypatch.setattr(registro.requests, "get", falha)
    res = registro.checar_http(8080)
    assert res == {"http_ok": False, "http_status": None, "http_ms": None, "erro": "ConnectionError"}


# ---------- processos ----------

def test_ppid_e_rss_lidos_do_proc(tmp_path):
    (tmp_path / "42").mkdir()
    (tmp_path / "42" / "stat").write_text("42 (python3 x) S 7 42 42 0 -1 0 0 0")
    (tmp_path / "42" / "status").write_text("Name: python3\nVmRSS:\t   4096 kB\n")
    assert registro.ppid(42, proc_dir=str(tmp_path)) == 7
    assert registro.ppid(99, proc_dir=str(tmp_path)) is None


def test_amostra_e_serializavel(tmp_path):
    r = Registro(str(tmp_path / "m.jsonl"))
    r.gravar({"t": 1.0, "servicos": {"w": {"http_ok": True}}})
    linha = (tmp_path / "m.jsonl").read_text().strip()
    assert json.loads(linha)["servicos"]["w"]["http_ok"] is True


def test_estatisticas_reduz_a_serie_e_resume_servicos():
    amostras = []
    for i in range(100):
        sv = {"web": {"estado": "RUNNING" if i % 4 else "BACKOFF", "http_ok": i % 2 == 0, "cpu": 2.0, "ram_mb": 10.0},
              "pg": {"estado": "RUNNING", "cpu": 1.0}}
        amostras.append({"t": 1000.0 + i * 10, "cpu_termux": float(i), "ram_pct": 50.0,
                         "rss_agente_kb": 20480, "rss_supervisord_kb": None, "servicos": sv})
    est = registro.estatisticas(amostras, 1000.0, 2000.0, pontos=10)
    assert len(est["serie"]) == 10
    assert est["serie"][0]["cpu"] == 4.5 and est["serie"][0]["agente_mb"] == 20.0
    assert est["serie"][0]["supervisord_mb"] is None
    web = est["servicos"]["web"]
    assert web["rodando_pct"] == 75.0 and web["http_ok_pct"] == 50.0 and web["cpu_media"] == 2.0
    assert web["ultimo_estado"] == "RUNNING" and web["amostras"] == 100
    assert est["servicos"]["pg"]["http_ok_pct"] is None  # banco não tem verificação HTTP
    assert est["amostras_total"] == 100 and est["cobertura_pct"] == 100.0


def test_estatisticas_janela_maior_que_o_registro():
    amostras = [{"t": 9000.0 + i * 10, "cpu_termux": 1.0} for i in range(6)]
    est = registro.estatisticas(amostras, 0.0, 9060.0, pontos=300)
    assert est["primeira"] == 9000.0 and est["amostras_total"] == 6
    assert est["cobertura_pct"] < 1 and est["servicos"] == {}


def test_estatisticas_sem_amostras():
    est = registro.estatisticas([], 0.0, 3600.0)
    assert est["serie"] == [] and est["primeira"] is None and est["cobertura_pct"] == 0.0
