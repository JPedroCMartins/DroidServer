# DroidServer

Transforme smartphones Android antigos — **sem root** — em nós de um pequeno cluster de servidores Linux.

Um servidor **Host** (Flask + Socket.IO) controla vários **Nodes** Android. Em cada Node, um agente Python rodando no [Termux](https://termux.dev/) cria ambientes Linux com `proot-distro` (Alpine, recomendado, ou Debian), chamados **Workers**, e os mantém de pé com o **Supervisor**. Tudo é operado por um painel web com métricas em tempo real e terminal interativo no navegador.

> Projeto de TCC em Engenharia da Computação (Uninorte, Manaus — 2026). A documentação acadêmica está em [`docs/obsidian-valt/`](docs/obsidian-valt/README.md).

## Sumário

- [Conceitos](#conceitos)
- [Arquitetura](#arquitetura)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Pré-requisitos](#pré-requisitos)
- [Instalação](#instalação)
- [Uso](#uso)
- [Configuração](#configuração)
- [API e eventos](#api-e-eventos)
- [Logs e diagnóstico](#logs-e-diagnóstico)
- [Testes](#testes)
- [Segurança e limitações](#segurança-e-limitações)

## Conceitos

| Termo | O que é |
|---|---|
| **Host** | Computador que roda `desktop/` — o plano de controle, com o painel web na porta 5050 |
| **Node** | Um celular Android rodando o agente `android/node.py` dentro do Termux |
| **Worker** | Um ambiente Linux (`proot-distro`) dentro de um Node, registrado como serviço no Supervisor |
| **Tarefa** | Ordem do Host para um Node (`criar_worker` ou `deletar_worker`), entregue no próximo sync |

## Arquitetura

```
 Navegador ──HTTP/WebSocket──►  ┌─────────────────────────────┐
                                │        HOST (desktop/)       │
                                │  Flask + Flask-SocketIO      │
                                │  · SPA (Tailwind + xterm.js) │
                                │  · /api/node_sync, /api/*    │
                                │  · retransmissão do terminal │
                                └──────────────▲──────────────┘
                                               │  POST /api/node_sync a cada 10 s
                                               │  + WebSocket (terminal)
                         ┌─────────────────────┴─────────────────────┐
                         │      NODE Android (android/, no Termux)    │
                         │  NodeAgent ─ polling, fila de tarefas      │
                         │  WorkerManager ─ proot-distro + Supervisor │
                         │  TerminalManager ─ PTY ↔ WebSocket         │
                         │  SystemMonitor ─ CPU/RAM via /proc         │
                         │   ┌─────────┐ ┌─────────┐ ┌─────────┐      │
                         │   │ Worker  │ │ Worker  │ │ Worker  │      │
                         │   │ alpine  │ │ alpine  │ │ debian  │      │
                         │   └─────────┘ └─────────┘ └─────────┘      │
                         └───────────────────────────────────────────┘
```

Toda conexão é **iniciada pelo Node**: o Host nunca precisa alcançar o celular, o que funciona atrás de NAT e tolera as restrições de energia do Android.

### Sincronização (HTTP)

A cada 10 s o Node faz `POST /api/node_sync` com IP, Workers instalados, status de cada serviço (`supervisorctl status`), tarefa em execução, resultado das últimas operações e uso de CPU/memória. O Host responde com as **tarefas pendentes** daquele Node. A lista de Workers é **autoritativa do Node** — o painel apenas exibe o que o aparelho reporta.

### Métricas

| Métrica | Fonte | Observação |
|---|---|---|
| **CPU DroidServer** | soma de `utime+stime` de `/proc/<pid>/stat` de todos os processos do Termux | Sempre disponível; em % do aparelho inteiro (100% = todos os núcleos) |
| **CPU por Worker** | mesma soma, restrita ao processo do serviço no Supervisor, à sessão de terminal e a seus descendentes | Processos iniciados fora do DroidServer (ex.: um `proot-distro login` manual) não entram |
| **CPU aparelho** | `/proc/stat` (ou `top`) | Só aparece se o Android permitir; no Android 16 sem root é negado |
| **RAM** | `/proc/meminfo` | `MemTotal − MemAvailable` |

A CPU do DroidServer não enxerga outros aplicativos do celular.

O Host marca um Node como **Offline** após 25 s sem contato e o remove do painel após 180 s (se não houver tarefas pendentes para ele).

### Criação de um Worker

1. O painel envia `POST /deploy_worker`; o Host valida o alias e a distribuição e enfileira `criar_worker`.
2. No próximo sync, o Node recebe a tarefa e a executa numa thread separada (instalar pode levar minutos sem travar o polling).
3. O Node limpa resíduos do mesmo alias, roda `proot-distro install <distro> --override-alias <alias>`, grava `$PREFIX/etc/supervisor/conf.d/<alias>.conf` e recarrega o Supervisor.
4. O Supervisor mantém o Worker rodando com `proot-distro login [--isolated] <alias> -- /app/run_server.sh`, aplicando limites `ulimit` (arquivos abertos e processos).
5. O agente cria um `/app/run_server.sh` padrão (um loop ocioso) — **substitua-o pelo seu aplicativo**.
6. O resultado (✓/✗) aparece no painel no sync seguinte.

### Terminal (WebSocket)

```
xterm.js ─terminal_input─► Host ─cmd_to_<ip>_<alias>─► Node ─► PTY (proot-distro login)
xterm.js ◄output_for_<ip>_<alias>─ Host ◄terminal_output─ Node ◄─┘
```

O PTY é aberto na primeira tecla recebida, e o redimensionamento da janela é repassado via `terminal_resize` → `resize_to_<ip>_<alias>` (`TIOCSWINSZ`).

## Estrutura do projeto

```
DroidServer/
├── android/                  # Agente do Node (roda no Termux)
│   ├── node.py               # NodeAgent, WorkerManager, TerminalManager
│   ├── sysinfo.py            # CPU/memória via /proc (fallback: top)
│   ├── setup.sh              # Primeiro uso: pacotes, Supervisor, conexão, boot
│   ├── run.sh                # Inicia/para o agente (primeiro ou segundo plano)
│   ├── diagnostico.sh        # Coleta informações para depuração
│   ├── tests/test_node.py    # Testes com mocks (rodam fora do Android)
│   └── pyproject.toml
├── desktop/                  # Host (plano de controle)
│   ├── main.py               # Ponto de entrada — porta 5050
│   ├── app/
│   │   ├── __init__.py       # create_app, Socket.IO e logs
│   │   ├── routes.py         # Páginas, API REST e eventos Socket.IO
│   │   └── templates/
│   │       └── index.html    # SPA: Dashboard, Node e Terminal
│   ├── tests/test_routes.py
│   └── pyproject.toml
└── docs/
    ├── obsidian-valt/        # Documentação do TCC (Obsidian)
    └── artigo_nao_finalizado.odt
```

## Pré-requisitos

**Host**
- Linux (testado em Debian), Python 3.12+ e [uv](https://docs.astral.sh/uv/)
- Acesso à internet no navegador (o painel carrega Tailwind, xterm.js e Socket.IO de CDNs)

**Node**
- Android 7+ com [Termux](https://f-droid.org/packages/com.termux/) instalado pelo **F-Droid** ou GitHub (a versão da Play Store está desatualizada)
- Celular e Host na **mesma rede**
- Opcional: [Termux:Boot](https://f-droid.org/packages/com.termux.boot/) para iniciar o agente ao ligar o aparelho

O `setup.sh` instala o restante (`python`, `proot-distro`, `supervisor`, `python-socketio[client]`, `requests`).

## Instalação

### 1. Host

```bash
cd desktop
uv sync
uv run python main.py
```

O painel fica em `http://<ip-do-host>:5050`. Libere a porta 5050 no firewall, se houver.

O Host também sobe sem terminal interativo (systemd, `nohup`), pois o servidor Werkzeug é iniciado com `allow_unsafe_werkzeug=True`. Isso é suficiente para um protótipo em LAN; em produção, prefira gunicorn com eventlet ou gevent.

### 2. Node (no Termux)

```bash
pkg install -y git
git clone <url-deste-repositório> DroidServer
cd DroidServer
bash android/setup.sh
```

O `setup.sh` pode ser executado de novo sem problemas. Ele:

1. instala os pacotes base e o Supervisor (via `pip`, com o `pkg` como alternativa);
2. gera ou ajusta o `$PREFIX/etc/supervisord.conf` — usando HTTP em `127.0.0.1:9001` com senha quando o Python do Termux não tem `os.link()` — e inicia o `supervisord`;
3. instala as dependências do agente e testa os imports;
4. pergunta IP, porta e token do Host, salva em `~/.config/droidserver/env` (modo 600) e testa a conexão;
5. opcionalmente cria um container Alpine de teste e configura o início automático com o Termux:Boot.

Depois, inicie o agente:

```bash
bash android/run.sh
```

| Comando | Efeito |
|---|---|
| `bash android/run.sh` | Primeiro plano (Ctrl+C encerra) |
| `bash android/run.sh -d` | Segundo plano, com `termux-wake-lock` e reinício automático |
| `bash android/run.sh status` | Mostra se o agente está rodando |
| `bash android/run.sh stop` | Encerra o agente em segundo plano |

O `run.sh` garante que o `supervisord` esteja de pé e reinicia o agente se ele cair (espera exponencial de 2 s a 60 s).

### Mantendo o Node vivo

O Android encerra processos em segundo plano agressivamente. Para um Node estável:

- desative a otimização de bateria do Termux (*Configurações → Apps → Termux → Bateria → Sem restrições*);
- use `run.sh -d`, que ativa o `termux-wake-lock`;
- **Android 12 ou superior:** desative o *phantom process killer* (nas opções de desenvolvedor, "Desativar restrições de processos filhos", ou via ADB), senão o Termux pode ser encerrado com `signal 9`. Veja [termux-app#2366](https://github.com/termux/termux-app/issues/2366).

## Uso

1. Acesse `http://<host>:5050`. O **Dashboard** mostra os Nodes, se estão online e o uso de CPU/RAM de cada um.
2. Clique em **Gerenciar Workers** para abrir a página do Node.
3. Escolha a distribuição (**Alpine**, recomendada: ~50 MB e pronta em segundos; ou **Debian**, ~150 MB, quando o software exigir glibc/`apt`), informe um alias (`[A-Za-z0-9_-]`, até 64 caracteres) e clique em **Criar Container**. A opção **Isolar do host** (`--isolated`, ativada por padrão) impede o Worker de enxergar o *home* do Termux e o armazenamento do aparelho.
4. Acompanhe "Em processamento" e "Últimas operações"; o Worker aparece como `RUNNING` quando o Supervisor o inicia.
5. Clique em **Abrir terminal** para uma sessão interativa dentro do Worker, ou no ícone de lixeira para removê-lo.

Para rodar sua aplicação, entre no terminal do Worker, instale o necessário e substitua `/app/run_server.sh` por um script que inicie seu serviço em primeiro plano (sem `&`), para que o Supervisor consiga monitorá-lo.

## Configuração

### Variáveis de ambiente

| Variável | Onde | Padrão | Descrição |
|---|---|---|---|
| `DROID_HOST_IP` | Node | `192.168.1.10` | IP do Host |
| `DROID_HOST_PORT` | Node | `5050` | Porta do Host |
| `DROID_TOKEN` | Node | vazio | Token enviado no sync |
| `DROID_LOG_FILE` | Node | `~/.config/droidserver/logs/node.log` | Arquivo de log do agente |
| `DROID_ULIMIT_NOFILE` | Node | `4096` | Limite de arquivos abertos por Worker (`0` desativa) |
| `DROID_ULIMIT_NPROC` | Node | `1024` | Limite de processos por Worker (`0` desativa) |
| `DROID_API_TOKEN` | Host | vazio | Se definido, só aceita Nodes que enviem o mesmo token |
| `DROID_BIND` | Host | `0.0.0.0` | Endereço em que o Host escuta |
| `DROID_PORT` | Host | `5050` | Porta do Host |
| `DROID_DEBUG` | Host | `0` | `1` liga o modo debug — só aceito com `DROID_BIND=127.0.0.1` |
| `DROID_SECRET_KEY` | Host | aleatória | Chave de sessão do Flask |
| `DROID_LOG_DIR` | Host | `desktop/logs/` | Diretório de logs do Host |

No Node, as variáveis de conexão ficam salvas em `~/.config/droidserver/env` e são carregadas pelo `run.sh`.

### Constantes no código

| Constante | Arquivo | Valor | Descrição |
|---|---|---|---|
| `POLL_INTERVAL` | `android/node.py` | 10 s | Intervalo entre syncs |
| `INSTALL_TIMEOUT` | `android/node.py` | 1200 s | Tempo máximo do `proot-distro install` |
| `IMAGENS_PERMITIDAS` | `node.py` e `routes.py` | alpine, debian | Distribuições aceitas (mantenha iguais nos dois) |
| `STALE_TIMEOUT` | `desktop/app/routes.py` | 25 s | Sem contato até virar Offline |
| `PRUNE_TIMEOUT` | `desktop/app/routes.py` | 180 s | Offline até sair do painel |

## API e eventos

### HTTP

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/`, `/node/<ip>`, `/node/<ip>/worker/<alias>` | SPA (as telas são resolvidas no navegador) |
| `GET` | `/api/nodes` | Estado de todos os Nodes |
| `GET` | `/api/node/<ip>` | Estado de um Node (404 se desconhecido) |
| `POST` | `/api/node_sync` | Sync do Node; responde `{"status": "ok", "tarefas": [...]}` |
| `POST` | `/deploy_worker` | Form `ip`, `alias`, `imagem`, `isolado` → enfileira `criar_worker` |
| `GET` | `/node/<ip>/worker/<alias>/delete` | Enfileira `deletar_worker` |

### Socket.IO

| Evento | Direção | Payload |
|---|---|---|
| `node_updated` | Host → painéis | `{ip}` — o painel recarrega os dados |
| `terminal_input` | Navegador → Host | `{ip, alias, input}` |
| `terminal_resize` | Navegador → Host | `{ip, alias, cols, rows}` |
| `terminal_output` | Node → Host | `{ip, alias, output}` |
| `cmd_to_<ip>_<alias>` | Host → Node | `{input}` |
| `resize_to_<ip>_<alias>` | Host → Node | `{cols, rows}` |
| `output_for_<ip>_<alias>` | Host → Navegador | `{output}` |

## Logs e diagnóstico

| Componente | Local |
|---|---|
| Setup | `~/.config/droidserver/logs/setup-<data>.log` (um por execução) |
| Agente | `~/.config/droidserver/logs/node.log` (rotativo, 2 MB × 5) |
| Agente em segundo plano (stdout) | `~/.config/droidserver/logs/agent.out` |
| Supervisor | `$PREFIX/var/log/supervisor/supervisord.log` |
| Cada Worker | `$PREFIX/var/log/supervisor_<alias>_{out,err}.log` |
| Host | `desktop/logs/droidserver.log` (rotativo, 2 MB × 5) |

Para coletar tudo de uma vez no celular:

```bash
bash android/diagnostico.sh
```

Para ver os serviços do Supervisor:

```bash
supervisorctl -c $PREFIX/etc/supervisord.conf status
```

## Testes

```bash
cd desktop && uv run pytest -v
```

```bash
cd android && uv run pytest -v
```

A suíte do Host usa o `test_client` do Flask e o `socketio.test_client`; a do agente usa `monkeypatch` em `subprocess`, `pty` e `requests`, então roda em qualquer Linux, sem Termux.

São 93 testes (35 no Host e 58 no agente), incluindo testes de regressão para a perda de resultados no sync, o uso do `supervisord.conf` correto e o fechamento das sessões de PTY.

## Segurança e limitações

O DroidServer é um protótipo acadêmico para uso **em rede local confiável**:

- o painel **não tem autenticação** — qualquer pessoa na rede pode criar ou apagar Workers e abrir terminais;
- o Host aceita qualquer origem no Socket.IO (`cors_allowed_origins="*"`) e o token trafega sem TLS. O modo debug fica desligado por padrão e só pode ser ligado escutando em `127.0.0.1`;
- os eventos de terminal são enviados a todos os clientes Socket.IO conectados;
- o PRoot isola apenas o sistema de arquivos: Workers compartilham rede, processos, CPU e memória com o aparelho (sem `cgroups`), e o `ptrace` adiciona sobrecarga em operações de E/S;
- o Node é identificado pelo IP; mudanças de DHCP geram registros duplicados;
- o estado do Host fica em memória e é perdido ao reiniciá-lo (os Nodes se registram de novo em até 10 s).
