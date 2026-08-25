# DroidServer

Orquestração de cluster a partir de dispositivos Android (Termux). Um servidor **desktop** (Flask + Socket.IO) funciona como host e controla vários **nodes** Android, onde cada node executa containers leves via `proot-distro` (ex.: Alpine) chamados de **workers**. Tudo é gerenciado por uma interface web com terminal interativo.

## Arquitetura

```
┌───────────────────────────────┐         ┌──────────────────────────────┐
│          DESKTOP (Host)       │         │        ANDROID (Node)        │
│                               │  HTTP   │                              │
│  Flask + Flask-SocketIO       │◄────────│  NodeAgent (node.py)         │
│  - Dashboard web (Bootstrap)  │  poll   │  - Poll /api/node_sync 10s   │
│  - API /api/node_sync         │ ───────►│  - Socket.IO client          │
│  - WebSocket (terminais)      │ SocketIO│  - WorkerManager (proot)     │
│                               │◄───────►│  - TerminalManager (PTY)     │
└───────────────────────────────┘         └──────────────────────────────┘
```

### Fluxo de comunicação

1. **Sincronização (HTTP):** cada node faz `POST /api/node_sync` a cada 10s informando IP, status e workers instalados. O host responde com as **tarefas pendentes** (criar/deletar worker) para o node executar.
2. **Terminal (WebSocket):** o navegador emite `terminal_input` → o host repassa como `cmd_to_<ip>_<alias>` → o node injeta o comando no PTY do container → a saída retorna como `terminal_output` → `output_for_<ip>_<alias>` → xterm.js no navegador.

### Fluxo de deploy de um worker

O host enfileira a tarefa `criar_worker` → o node executa `proot-distro install` com o alias escolhido → gera um arquivo `.conf` em `$PREFIX/etc/supervisor/conf.d/` → o **Supervisor** inicia e mantém o container rodando (`proot-distro login <alias> -- /app/run_server.sh`). O agente também cria um `run_server.sh` padrão dentro de cada container — substitua pelo seu aplicativo.

## Estrutura do projeto

```
DroidServer/
├── android/                  # Agente que roda no dispositivo Android (Termux)
│   ├── node.py               # NodeAgent: polling, WebSocket, workers e PTY
│   ├── setup.sh              # Script de primeiro uso (instala e configura tudo)
│   ├── run.sh                # Inicia o agente carregando a configuração salva
│   ├── pyproject.toml        # Dependências (python-socketio, requests)
│   └── uv.lock
└── desktop/                  # Servidor host (controlador do cluster)
    ├── main.py               # Ponto de entrada — roda na porta 5050
    ├── android_setup.sh      # Instala dependências no Android
    ├── app/
    │   ├── __init__.py       # Criação da app Flask + SocketIO
    │   ├── routes.py         # Rotas HTTP, API e eventos SocketIO
    │   └── templates/        # Páginas web (Bootstrap + xterm.js)
    │       ├── index.html        # Dashboard com lista de nodes
    │       ├── node_detail.html  # Gerencia workers do node
    │       └── terminal.html     # Terminal web do worker
    └── pyproject.toml        # Dependências (flask, flask-socketio)
```

## Pré-requisitos

- **Desktop (Host):** Python 3.12+, [uv](https://docs.astral.sh/uv/) e `git`
- **Android (Node):**
  - [Termux](https://termux.dev/) (F-Droid)
  - `proot-distro`
  - `supervisor` + `supervisorctl`
  - Python 3 + dependências do agente (`python-socketio`, `requests`)

## Instalação

### 1. Servidor host (desktop)

```bash
cd desktop
uv sync
uv run python main.py
```

O host fica disponível em `http://0.0.0.0:5050`.

### 2. Node Android (Termux)

No celular, com o [Termux](https://termux.dev/) instalado, copie o repositório para o aparelho (ex.: `git clone` ou via adb) e rode o script de **primeiro uso** — ele instala tudo e configura a conexão:

```bash
bash android/setup.sh
```

O script instala os pacotes (`git`, `python`, `proot-distro`, `supervisor`), as dependências do agente, garante que o **Supervisor** leia os arquivos de serviço em `$PREFIX/etc/supervisor/conf.d/`, inicia o `supervisord` e salva a configuração em `~/.config/droidserver/env`.

Inicie o agente com o wrapper (já carrega IP/porta/token salvos):

```bash
bash android/run.sh
```

Ou configure manualmente via variáveis de ambiente:

```bash
export DROID_HOST_IP="192.168.1.10"   # IP do desktop na rede
export DROID_HOST_PORT="5050"         # porta do host (opcional)
export DROID_TOKEN=""                 # token opcional, exigido se o host tiver DROID_API_TOKEN
python3 node.py                       # dentro da pasta android/
```

## Variáveis de ambiente

| Variável              | Onde                | Descrição                                             |
|-----------------------|---------------------|-------------------------------------------------------|
| `DROID_HOST_IP`       | Node (android)      | IP do servidor host (padrão `192.168.1.10`)           |
| `DROID_HOST_PORT`     | Node (android)      | Porta do host (padrão `5050`)                         |
| `DROID_TOKEN`         | Node (android)      | Token enviado na sincronização (opcional)             |
| `DROID_API_TOKEN`     | Host (desktop)      | Se definido, exige o token nos nodes (`/api/node_sync`) |

Sem `DROID_API_TOKEN`, o host funciona aberto como antes. Com o token definido, apenas nodes que enviam o mesmo `DROID_TOKEN` são registrados.

## Testes

Os dois lados do projeto têm suíte de testes com `pytest`:

```bash
# Host (rotas HTTP, detecção de offline, fila de tarefas, eventos Socket.IO)
cd desktop && uv run pytest -v

# Agente Android (config, WorkerManager, TerminalManager e polling com mocks)
cd android && uv run pytest -v
```

A suíte do desktop usa `test_client` do Flask e `socketio.test_client` para validar o encaminhamento dos eventos de terminal (`terminal_input`, `terminal_resize`, `terminal_output`) sem precisar de servidor real. A do android usa mocks (`monkeypatch`) de `subprocess`, `pty` e `requests`, então não requer Termux/proot-distro para rodar.

## Uso

1. Acesse `http://<host>:5050` no navegador — o dashboard lista os nodes online.
2. Clique em **Gerenciar Workers** para abrir a página do node.
3. Crie um container informando o alias (ex.: `alpine_bd`) ou apague os existentes.
4. Clique em **Abrir Terminal** para abrir um terminal interativo (xterm.js) dentro do container via WebSocket.

## Pontos de configuração

| Parâmetro          | Local                                        | Descrição                               |
|--------------------|----------------------------------------------|-----------------------------------------|
| Conexão do node    | env vars (ver acima)                         | IP/porta/token do host                  |
| `imagem`           | `desktop/app/routes.py` (`deploy_worker`)    | Imagem proot-distro dos workers         |
| Intervalo de poll  | `android/node.py` (`POLL_INTERVAL`)          | Tempo entre sincronizações (10s)        |
| Timeout de offline | `desktop/app/routes.py` (`STALE_TIMEOUT`)    | Segundos sem contato até virar Offline  |
