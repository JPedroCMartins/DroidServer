# Aba Serviço amigável (ajuda "?" + visão geral) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Na aba Serviço de cada Worker, mostrar uma visão geral (endereço testável, falhas do dia, CPU/RAM/disco, distribuição, último salvamento) e uma ajuda "?" que ensina a escrever o `/app/run.sh`.

**Architecture:** O agente (`android/servico.py`, `android/sysinfo.py`, `android/node.py`) acrescenta campos ao estado de cada serviço que já viaja no *sync* (`servicos[alias]`); o Host (`desktop/app/routes.py`) ganha uma rota que testa o endereço do serviço a partir do PC; o painel (`desktop/app/templates/index.html`, `viewServico`) exibe os campos e um painel lateral de ajuda com conteúdo estático. Nenhum formato novo: a porta é declarada num comentário do próprio `run.sh`.

**Tech Stack:** Python 3 (agente e Host Flask/Flask-SocketIO), pytest, HTML + JS puro com Tailwind local (painel).

**Spec:** `docs/superpowers/specs/2026-11-16-aba-servico-amigavel-design.md` (abordagem **A**; seção 6 tem as decisões).

## Global Constraints

- Escopo = abordagem A: **sem** assistente, **sem** repositório Git, **sem** variáveis de ambiente, **sem** envio de arquivos.
- A porta **não** é descoberta automaticamente (o Android nega `/proc/net/tcp` sem *root*): vem do cabeçalho `# droidserver: porta=<n>` no `run.sh`.
- Texto da interface e mensagens em português; todo conteúdo dinâmico no HTML passa por `esc()`.
- Painel sem dependências externas (nada de CDN); só o que já está em `desktop/app/static/vendor/`.
- O `du` do Worker nunca roda no caminho do *sync*: em *thread*, com cache de 600 s.
- **Aparelho: só o Motorola moto e40 (192.168.1.100).** O POCO X6 Pro é o celular pessoal do usuário e não entra no projeto. A E7 foi adiada (pendência P1 do plano de ação), então o moto está livre: o agente novo pode ser enviado a ele na Task 7. Não tocar no Worker `portfolio-web` do usuário.
- Nada de estimativas de tempo em documentos.
- Depois de mudar o vault, regenerar `docs/DroidServer_TCC_artigo.docx` e validá-lo (ver Task 7).

## Review Focus

1. `run.sh` sem cabeçalho, ou com `porta=abc`, `porta=0`, `porta=70000` → `porta` é `None` e a visão geral mostra "porta não informada" com o "?" (testes na Task 1).
2. Aliases com prefixo comum (`api` e `api2`) no log do supervisord → falhas contadas só para o alias exato (teste na Task 2).
3. "Testar" com porta não informada, serviço parado ou Node fora do ar → resposta em ≤ 3 s com mensagem clara, sem travar o Host (testes na Task 5).
4. Worker Debian grande → primeira consulta do disco devolve `None` ("calculando…") sem bloquear; o valor aparece no *sync* seguinte (teste na Task 3).
5. Agente antigo, sem os campos novos → o painel mostra "—" nos campos e não quebra (verificação no navegador, Task 6).

---

### Task 1: Cabeçalho do `run.sh`, distribuição e último salvamento

**Files:**
- Modify: `android/servico.py` (`EXEMPLO` na linha 67; `estado_servicos` na linha 401)
- Test: `android/tests/test_servico.py`

**Interfaces:**
- Produces: `ler_metadados(conteudo: str | None) -> dict` (chaves `porta: int | None`); `distro(alias: str) -> str | None`; novos campos em `estado_servicos(...)[alias]`: `porta`, `distro`, `script_salvo_em` (epoch `float | None`).

- [ ] **Step 1: Testes que falham**

```python
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
```

- [ ] **Step 2:** `cd android && uv run --extra dev pytest tests/test_servico.py -q -k "metadados or porta_distro or exemplo_declara"` → FAIL (`ler_metadados` não existe).

- [ ] **Step 3: Implementar**
  - `ler_metadados`: procura, só nas linhas de comentário, `#\s*droidserver:\s*(.*)` (sem diferenciar maiúsculas), lê pares `chave = valor`; `porta` vale só se for inteiro em 1–65535.
  - `distro`: `PRETTY_NAME` de `<rootfs>/etc/os-release` (ou `/usr/lib/os-release`), sem aspas; guardar em cache por alias (dicionário do módulo).
  - `script_salvo_em`: `os.path.getmtime` do `run.sh`, `None` se não existir (usar `_dentro_do_container`, links não contam).
  - `EXEMPLO`: logo após o `#!/bin/sh`, a linha `# droidserver: porta=8080` com um comentário explicando que ela informa ao painel onde o serviço escuta.

- [ ] **Step 4:** mesmo comando do Step 2 → PASS; depois a suíte inteira do agente → PASS.

- [ ] **Step 5:** `git commit -m "feat(servico): porta declarada no run.sh, distribuição e último salvamento no estado"`

---

### Task 2: Falhas do dia pelo log do supervisord

**Files:**
- Modify: `android/servico.py` (perto de `status_supervisor`, linha 374; `estado_servicos`)
- Test: `android/tests/test_servico.py`

**Interfaces:**
- Consumes: `ultimas_linhas(caminho, n, bloco)` (já existe, linha 525).
- Produces: `supervisord_log() -> str` (caminho lido de `logfile=` no `supervisord.conf`; padrão `$PREFIX/var/log/supervisor/supervisord.log`); `falhas_do_dia(aliases: list[str], hoje: str | None = None) -> dict[str, dict]` com `{"falhas_hoje": int, "ultima_falha": {"quando": "HH:MM:SS", "codigo": int, "motivo": str} | None}`; mesmos campos em `estado_servicos(...)[alias]`.

- [ ] **Step 1: Testes que falham**

```python
LOG_SUP = """2026-11-15 23:59:01,1 WARN exited: w1 (exit status 1; not expected)
2026-11-16 18:07:45,172 WARN exited: w1 (exit status 127; not expected)
2026-11-16 18:07:50,994 INFO spawned: 'w1' with pid 24542
2026-11-16 18:08:00,000 WARN exited: w12 (exit status 1; not expected)
2026-11-16 18:09:00,000 INFO exited: w1 (exit status 0; expected)
2026-11-16 18:10:00,000 INFO stopped: w1 (terminated by SIGTERM)
"""

def test_falhas_do_dia(termux):
    conf = termux / "etc/supervisord.conf"
    conf.write_text(f"[supervisord]\nlogfile={termux}/var/log/supervisor/supervisord.log\n")
    log = termux / "var/log/supervisor/supervisord.log"
    log.parent.mkdir(parents=True); log.write_text(LOG_SUP)
    r = servico.falhas_do_dia(["w1", "w12", "w9"], hoje="2026-11-16")
    assert r["w1"] == {"falhas_hoje": 1, "ultima_falha":
                       {"quando": "18:07:45", "codigo": 127, "motivo": "comando não encontrado"}}
    assert r["w12"]["falhas_hoje"] == 1 and r["w9"] == {"falhas_hoje": 0, "ultima_falha": None}

def test_falhas_sem_log(termux):
    assert servico.falhas_do_dia(["w1"])["w1"] == {"falhas_hoje": 0, "ultima_falha": None}
```

- [ ] **Step 2:** rodar os dois testes → FAIL.

- [ ] **Step 3: Implementar.** (A partir desta tarefa, `estado_servicos` também consulta o log e o disco; nos testes que já existem, o *fixture* `comandos` devolve saída vazia para o `du`, o que mantém o disco em `None` — esperado.) Ler as últimas 3000 linhas uma vez por chamada (não uma vez por alias); casar `^(\d{4}-\d\d-\d\d) (\d\d:\d\d:\d\d),\d+ \w+ exited: (\S+) \(exit status (\d+); not expected\)` com igualdade exata do alias. Motivos: `{126: "sem permissão de execução", 127: "comando não encontrado", 137: "encerrado pelo sistema (memória ou kill)", 143: "encerrado (SIGTERM)"}`, demais → `"erro no programa (código N)"`. `hoje` padrão = `time.strftime("%Y-%m-%d")`. `estado_servicos` chama `falhas_do_dia(aliases)` uma vez e mescla.

- [ ] **Step 4:** testes → PASS; suíte do agente → PASS.

- [ ] **Step 5:** `git commit -m "feat(servico): falhas do dia e última falha a partir do log do supervisord"`

---

### Task 3: Disco do Worker em segundo plano

**Files:**
- Modify: `android/servico.py`
- Test: `android/tests/test_servico.py`

**Interfaces:**
- Produces: `class DiscoCache(validade: float = 600, relogio=time.monotonic)` com `mb(alias: str) -> float | None` (devolve o último valor conhecido e dispara, se vencido e sem cálculo em andamento, uma *thread* com `du -sk <rootfs>`); instância de módulo `disco = DiscoCache()`; campo `disco_mb` em `estado_servicos(...)[alias]`.

- [ ] **Step 1: Teste que falha**

```python
def test_disco_calcula_em_segundo_plano(termux, monkeypatch):
    calls = []
    def fake_run(cmd, **kw):
        calls.append(cmd); time.sleep(0.2)
        return _Proc(0, out="51200\t/x\n")
    monkeypatch.setattr("subprocess.run", fake_run)
    agora = [1000.0]
    d = servico.DiscoCache(validade=600, relogio=lambda: agora[0])
    assert d.mb("w1") is None                      # não bloqueia na 1ª consulta
    for _ in range(50):
        if d.mb("w1") is not None: break
        time.sleep(0.02)
    assert d.mb("w1") == 50.0 and len(calls) == 1  # 51200 kB -> 50 MB, um du só
    agora[0] += 601
    d.mb("w1"); time.sleep(0.3)
    assert len(calls) == 2                          # venceu: recalcula
```

- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3:** implementar com `threading.Lock` e um conjunto de aliases em cálculo; `du -sk` com `timeout=300`; falha do `du` mantém o valor anterior.
- [ ] **Step 4:** teste → PASS; suíte → PASS.
- [ ] **Step 5:** `git commit -m "feat(servico): disco do worker calculado em segundo plano com cache de 10 min"`

---

### Task 4: RAM do serviço (árvore de processos)

**Files:**
- Modify: `android/sysinfo.py` (após `descendentes`, linha 191); `android/node.py` (`_poll_once`, linha 810)
- Test: `android/tests/test_node.py`

**Interfaces:**
- Consumes: `ler_processos(proc_dir)`, `descendentes(processos, raizes)` (já existem).
- Produces: `memoria_grupos(grupos: dict[str, list[int]], proc_dir=None) -> dict[str, float]` (MB, soma de `VmRSS` de raízes + descendentes, 1 casa decimal); no payload do *sync*, `servicos[alias]["ram_mb"]` para os aliases com pid de serviço (só o serviço, não o terminal).

- [ ] **Step 1: Testes que falham**

```python
def test_memoria_grupos_soma_a_arvore(tmp_path):
    for pid, ppid, rss in [(10, 1, 1024), (11, 10, 2048), (12, 11, 1024), (20, 1, 4096)]:
        d = tmp_path / str(pid); d.mkdir()
        (d / "stat").write_text(f"{pid} (x) S {ppid} 0 0 0 0 0 0 0 0 0 5 5 0 0")
        (d / "status").write_text(f"Name:\tx\nVmRSS:\t   {rss} kB\n")
    import sysinfo
    assert sysinfo.memoria_grupos({"w1": [10], "w2": [20], "w3": [99]}, proc_dir=str(tmp_path)) == \
        {"w1": 4.0, "w2": 4.0, "w3": 0.0}
```

e, no teste existente `test_poll_once_envia_cpu_dos_workers_incluindo_terminal`, monkeypatch de `node.memoria_grupos` devolvendo `{"w1": 21.5}` e a asserção `payload["servicos"]["w1"]["ram_mb"] == 21.5`.

- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3:** implementar `memoria_grupos` (processo sem `status` legível conta 0); em `node.py`, importar pelo nome (`from sysinfo import ProcessCPUMonitor, SystemMonitor, memoria_grupos`, para o monkeypatch `node.memoria_grupos` do teste valer) e, em `_poll_once`, chamar com `{alias: [pid] for alias, pid in worker_pids.items()}` e mesclar em `servicos`.
- [ ] **Step 4:** testes → PASS; suíte → PASS.
- [ ] **Step 5:** `git commit -m "feat(agente): RAM do serviço de cada worker no sync"`

---

### Task 5: Host — "Testar" o endereço do serviço

**Files:**
- Modify: `desktop/app/routes.py` (nova rota perto de `/api/node/<ip>/historico`, linha 516)
- Test: `desktop/tests/test_routes.py`

**Interfaces:**
- Consumes: `nodes_conectados[ip]["servicos"][alias]["porta"]` (Task 1), `_alias_valido`.
- Produces: `POST /api/node/<ip>/worker/<alias>/testar` → 200 com `{"ok": bool, "url": str|None, "status": int|None, "ms": float|None, "erro": str|None}`; 404 se Node/Worker desconhecido.

- [ ] **Step 1: Testes que falham**

```python
def _sync_com_porta(client, porta):
    client.post("/api/node_sync", json={"ip": "10.0.0.5", "workers": ["w1"],
                                        "servicos": {"w1": {"estado": "RUNNING", "porta": porta}}})

class _Resp:
    status = 200
    def __enter__(self): return self
    def __exit__(self, *a): return False

def test_testar_endereco_ok(client, monkeypatch):
    _sync_com_porta(client, 8080)
    urls = []
    monkeypatch.setattr(_routes().urllib.request, "urlopen",
                        lambda url, timeout=None: (urls.append((url, timeout)), _Resp())[1])
    r = client.post("/api/node/10.0.0.5/worker/w1/testar").get_json()
    assert r["ok"] is True and r["status"] == 200 and r["ms"] >= 0 and r["erro"] is None
    assert r["url"] == "http://10.0.0.5:8080/" and urls == [("http://10.0.0.5:8080/", 3)]

def test_testar_sem_porta(client):
    _sync_com_porta(client, None)
    r = client.post("/api/node/10.0.0.5/worker/w1/testar").get_json()
    assert r["ok"] is False and r["url"] is None and "porta não informada" in r["erro"]

@pytest.mark.parametrize("exc,trecho", [(ConnectionRefusedError(), "não respondeu"),
                                        (socket.timeout(), "3 s")])
def test_testar_recusado_e_timeout(client, monkeypatch, exc, trecho):
    _sync_com_porta(client, 8080)
    def falha(url, timeout=None):
        raise exc
    monkeypatch.setattr(_routes().urllib.request, "urlopen", falha)
    r = client.post("/api/node/10.0.0.5/worker/w1/testar").get_json()
    assert r["ok"] is False and trecho in r["erro"]

def test_testar_erro_http_ainda_prova_que_esta_no_ar(client, monkeypatch):
    _sync_com_porta(client, 8080)
    def http_404(url, timeout=None):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
    monkeypatch.setattr(_routes().urllib.request, "urlopen", http_404)
    r = client.post("/api/node/10.0.0.5/worker/w1/testar").get_json()
    assert r["ok"] is True and r["status"] == 404

def test_testar_node_ou_worker_desconhecido(client):
    _sync_com_porta(client, 8080)
    assert client.post("/api/node/10.9.9.9/worker/w1/testar").status_code == 404
    assert client.post("/api/node/10.0.0.5/worker/nope/testar").status_code == 404
```

(`socket` e `urllib.error` importados no topo do arquivo de testes.)

- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3:** implementar com `urllib.request.urlopen(url, timeout=3)`; uma resposta HTTP de erro (4xx/5xx) também prova que o serviço está no ar: `ok True` com o `status` dela.
- [ ] **Step 4:** testes → PASS; suíte do Host → PASS.
- [ ] **Step 5:** `git commit -m "feat(host): testar o endereço do serviço a partir do Host"`

---

### Task 6: Painel — visão geral, ajuda "?" e números de linha

**Files:**
- Modify: `desktop/app/templates/index.html` (`viewServico`, linha 1000; `mostrarEstado`; `ICON` na linha 164)

**Interfaces:**
- Consumes: campos `porta`, `distro`, `script_salvo_em`, `falhas_hoje`, `ultima_falha`, `disco_mb`, `ram_mb` (Tasks 1–4), `cpu_workers[alias]` (já existe), rota `testar` (Task 5).
- Já existe e fica como está: os botões Iniciar/Parar já se habilitam conforme o estado (`mostrarEstado`).
- Produces: `abrirAjuda(secao)` e `fecharAjuda()` (painel lateral); `ajudaServicoHtml()` (conteúdo estático); bloco "Visão geral" com ids `svEndereco`, `svFalhas`, `svRecursos`.

- [ ] **Step 1: Visão geral** no cartão de estado:
  - Endereço: `http://<ip>:<porta>` como link (`target="_blank" rel="noopener"`), botões "Abrir" e "Testar" (POST da Task 5; resultado ao lado: "✓ 200 em 38 ms" ou a mensagem de erro). Sem porta: "Porta não informada" + "?" que abre a ajuda na seção da porta.
  - "Falhas hoje: N · Última: 18:07 — comando não encontrado (127)" ou "Falhas hoje: 0".
  - "CPU x% · RAM y MB · Disco z MB (ou 'calculando…') · <distro> · run.sh salvo há <tempo relativo>"; qualquer campo ausente → "—". O `ram_mb` que vier só do *sync* é mantido quando uma `servico_resposta` chegar sem ele.
- [ ] **Step 2: Ajuda "?"**: botão "?" (com `aria-label="Ajuda"`) ao lado de `/app/run.sh`, das duas opções e do endereço; painel lateral à direita (tela cheia no celular), fecha com Esc, botão "×" e clique fora; foco vai para o painel ao abrir e volta ao "?" ao fechar. Seções com âncora: **Passo a passo** (arquivos em `/app` pelo Terminal → instalar pacotes com `apk add`/`apt install` → escrever o `run.sh` → declarar `# droidserver: porta=N` → "Salvar e reiniciar"), **Regras do run.sh** (primeiro plano, `exec` no último comando, sem `&`/`nohup`, *shebang* respeitado, sem link simbólico, porta exclusiva por aparelho), **Exemplos** (site estático com `python3 -m http.server`, API Python, Node.js, bot Python — cada um com o cabeçalho de porta quando houver), **Estados** (Rodando, Iniciando, Falhou, Parado, Aguardando run.sh), **Erros comuns** (127, 126, 137, "Address in use", sobe e cai), **Opções** (o que fazem os dois *checkboxes* e quando valem).
- [ ] **Step 3: Números de linha** no editor: coluna à esquerda sincronizada com a rolagem e com a quantidade de linhas, mesma fonte e altura de linha do `textarea`.
- [ ] **Step 4: Verificar no navegador** (Host reiniciado; o moto ainda com o agente antigo, antes da Task 7): a visão geral do `demo_api` do moto mostra "—" nos campos novos e "Porta não informada", sem erro no console (Review Focus 5); "?" abre e fecha (Esc, ×, clique fora) e o foco volta ao botão; "Testar" sem porta mostra a mensagem da Task 5; aparência em largura de celular (375 px). A verificação com dados reais fica para a Task 7.
- [ ] **Step 5:** `git commit -m "feat(painel): visão geral do serviço e ajuda '?' do run.sh"`

---

### Task 7: Validação no aparelho e documentação

**Files:**
- Modify: `README.md` (seção "Serviço do Worker"), `docs/obsidian-valt/08-prototipacao.md` (8.4.1), `docs/plano-proximos-passos.md` (Fase 2B), `docs/DroidServer_TCC_artigo.docx` (regenerado)

- [ ] **Step 1:** enviar `servico.py`, `sysinfo.py`, `node.py` e os testes ao **moto e40**; rodar a suíte lá → PASS; reiniciar o agente do moto.
- [ ] **Step 2:** no painel, com o moto: acrescentar `# droidserver: porta=8080` ao `run.sh` do `demo_api` → endereço aparece e "Testar" dá ✓ 200; criar um Worker de teste com `run.sh` = `exec comando_inexistente` → "Falhas hoje" sobe e a última falha diz "comando não encontrado (127)"; apagar o Worker de teste; disco aparece após o 2º *sync*; RAM coerente com o processo. Não tocar no Worker `portfolio-web` do usuário.
- [ ] **Step 3:** documentar o cabeçalho `# droidserver: porta=N`, a visão geral e a ajuda no README e na 8.4.1; marcar S1, S2, S3, S5 e S6 como feitos no plano.
- [ ] **Step 4:** `cd docs/gerador-docx && npm run gerar` e `uv run --with defusedxml --with lxml python <skill docx>/scripts/office/validate.py ../DroidServer_TCC_artigo.docx` → "All validations PASSED!".
- [ ] **Step 5:** `git commit -m "docs: aba Serviço amigável (visão geral e ajuda)"`.
