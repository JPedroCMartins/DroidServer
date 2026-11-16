# 8. Prototipação e Implementação

Este capítulo descreve o protótipo implementado no repositório DroidServer: seus componentes, o protocolo de comunicação e os principais fluxos.

## 8.1 Visão geral

Um Host (PC ou servidor) controla vários Nodes Android. Em cada aparelho, o Termux executa o agente e o `proot-distro`, que hospeda os Workers mantidos pelo Supervisor.

```mermaid
flowchart LR
    Admin(["Administrador<br/>(navegador)"])
    Host["Host<br/>Flask + Socket.IO<br/>:5050"]
    Admin -- "HTTP + WebSocket" --> Host

    subgraph A1["Node Android 01"]
        subgraph T1["Termux"]
            Ag1["Agente node.py"]
            Sup1["Supervisor"]
            subgraph P1["proot-distro"]
                W11["Worker<br/>alpine_api"]
                W12["Worker<br/>debian_bd"]
            end
            Sup1 --> W11
            Sup1 --> W12
            Ag1 -.PTY.-> W11
        end
    end

    subgraph A2["Node Android 02"]
        subgraph T2["Termux"]
            Ag2["Agente node.py"]
            Sup2["Supervisor"]
            subgraph P2["proot-distro"]
                W21["Worker"]
            end
            Sup2 --> W21
        end
    end

    Ag1 -- "POST /api/node_sync (10 s)<br/>+ WebSocket" --> Host
    Ag2 -- "POST /api/node_sync (10 s)<br/>+ WebSocket" --> Host
```

*Figura 1 — Arquitetura do DroidServer. As setas partem de quem inicia a conexão: o Host nunca abre conexões até os Nodes.*

## 8.2 Componentes

| Componente | Arquivo | Responsabilidade |
|---|---|---|
| Servidor Host | `desktop/app/__init__.py`, `desktop/main.py` | Cria a aplicação Flask, o Socket.IO e os *logs* rotativos; escuta em `0.0.0.0:5050` |
| API e eventos | `desktop/app/routes.py` | Registro de Nodes, fila de tarefas, detecção de *offline*, retransmissão do terminal |
| Painel (SPA) | `desktop/app/templates/index.html` | *Single Page Application* com três telas: Dashboard, Node e Terminal |
| Agente | `android/node.py` | Classes `Config`, `WorkerManager`, `TerminalManager` e `NodeAgent` |
| Métricas | `android/sysinfo.py` | CPU (delta de `/proc/stat` ou `top`) e memória (`/proc/meminfo`) |
| Instalação | `android/setup.sh` | Pacotes, Supervisor, `supervisord.conf`, dependências, conexão, Termux:Boot |
| Execução | `android/run.sh` | Inicia o agente em primeiro ou segundo plano com reinício automático |
| Diagnóstico | `android/diagnostico.sh` | Coleta estado do `/proc`, `proot-distro`, Supervisor e *logs* |

## 8.3 Protocolo de comunicação

### 8.3.1 Sincronização (HTTP, iniciada pelo Node)

A cada `POLL_INTERVAL = 10 s`, o agente envia:

```json
POST /api/node_sync
{
  "ip": "192.168.0.23",
  "status": "Online",
  "workers": ["alpine_api", "debian_bd"],
  "worker_status": {"alpine_api": "RUNNING", "debian_bd": "STARTING"},
  "tarefa_atual": {"acao": "criar_worker", "alias": "arch_dev", "imagem": "archlinux"},
  "resultados": [{"acao": "deletar_worker", "alias": "teste", "ok": true, "msg": "...", "ts": "14:02:11"}],
  "cpu": 23.4,
  "mem": {"total": 3876544512, "usado": 2147483648, "percent": 55.4},
  "token": "opcional"
}
```

O Host atualiza o registro do Node, emite `node_updated` aos painéis abertos e responde com as tarefas pendentes, esvaziando a fila daquele Node:

```json
{"status": "ok", "tarefas": [{"acao": "criar_worker", "alias": "arch_dev", "imagem": "archlinux", "isolado": true}]}
```

A lista de Workers é **autoritativa do Node**: o Host nunca a altera de forma otimista, apenas exibe o que o aparelho reporta.

### 8.3.2 Terminal (WebSocket)

| Origem → destino | Evento | Conteúdo |
|---|---|---|
| Navegador → Host | `terminal_input` | `{ip, alias, input}` |
| Host → Node | `cmd_to_<ip>_<alias>` | `{input}` |
| Navegador → Host | `terminal_resize` | `{ip, alias, cols, rows}` |
| Host → Node | `resize_to_<ip>_<alias>` | `{cols, rows}` |
| Node → Host | `terminal_output` | `{ip, alias, output}` |
| Host → Navegador | `output_for_<ip>_<alias>` | `{output}` |

```mermaid
sequenceDiagram
    participant B as Navegador (xterm.js)
    participant H as Host (Flask-SocketIO)
    participant N as Node (node.py)
    participant P as PTY → proot-distro login
    B->>H: terminal_input {ip, alias, "ls\r"}
    H->>N: cmd_to_<ip>_<alias> {input}
    Note over N: Abre o PTY na primeira entrada (pty.fork)
    N->>P: os.write(master_fd)
    P-->>N: saída (select + os.read)
    N->>H: terminal_output {ip, alias, output}
    H->>B: output_for_<ip>_<alias> {output}
```

*Figura 2 — Fluxo de uma tecla no terminal remoto.*

## 8.4 Ciclo de vida de um Worker

```mermaid
sequenceDiagram
    participant A as Administrador
    participant H as Host
    participant N as Node
    participant S as Supervisor
    A->>H: POST /deploy_worker {ip, alias, imagem, isolado}
    H->>H: valida alias/imagem e enfileira "criar_worker"
    N->>H: POST /api/node_sync
    H-->>N: tarefas: [criar_worker]
    N->>N: fila interna (thread) — não bloqueia o polling
    N->>N: limpa resíduos do alias; proot-distro install <imagem> --override-alias <alias>
    N->>S: grava conf.d/<alias>.conf; supervisorctl reread/update
    N->>N: injeta /app/run_server.sh (base64)
    N->>H: próximo sync: resultados [✓ criado], worker_status RUNNING
```

*Figura 3 — Criação de um Worker.*

O serviço gerado para o Supervisor tem a forma:

```ini
[program:alpine_api]
command=sh -c 'ulimit -n 4096 2>/dev/null; ulimit -u 1024 2>/dev/null; exec proot-distro login --isolated alpine_api -- /app/run_server.sh'
autostart=true
autorestart=true
startsecs=5
```

A remoção segue o caminho inverso: encerra a sessão de terminal, para o serviço, remove o `.conf`, encerra as sessões restantes do container (`proot-distro kill`), executa `proot-distro remove` — com novas tentativas, pois o comando falha de imediato se alguma sessão ainda segura o *lock* do container — e apaga os *logs*.

## 8.5 Decisões de projeto

| Decisão | Motivo | Consequência |
|---|---|---|
| *Polling* iniciado pelo Node | Funciona atrás de NAT; o Host não precisa conhecer nem alcançar o aparelho | Tarefas demoram até 10 s para começar |
| Fila de tarefas em *thread* | `proot-distro install` pode levar até 20 min (`INSTALL_TIMEOUT = 1200`) | O *sync* continua mesmo durante instalações |
| Supervisor em vez de processos soltos | Reinício automático; não há *systemd* no Android | Dependência extra; ajuste para Python sem `os.link()` |
| `--isolated` por padrão | Evita que o Worker veja o *home* do Termux e o `/sdcard` | Requer `proot-distro` recente |
| `ulimit` por Worker | Único limite disponível sem *cgroups* | Não limita CPU nem memória |
| Validação do alias (`^[A-Za-z0-9_-]{1,64}$`) no Host e no Node | O alias vira caminho, nome de serviço e nome de evento | Previne injeção de comandos e de caminhos |
| Estado do Host em memória | Simplicidade do protótipo | Reiniciar o Host apaga o registro (os Nodes se re-registram em 10 s) |
| Token opcional (`DROID_API_TOKEN`) | Restringir quais Nodes se registram | Enviado em texto claro (sem TLS) |

## 8.6 Garantia de qualidade

O projeto possui 86 testes automatizados com `pytest` (34 no Host e 52 no agente), usando o `test_client` do Flask, o `socketio.test_client` e *mocks* de `subprocess`, `pty`, `select` e `requests` — de modo que rodam em qualquer Linux, fora do Android. A suíte inclui testes de regressão para defeitos encontrados durante o desenvolvimento: perda de resultados de tarefas registrados durante uma sincronização, chamadas ao `supervisorctl` sem o arquivo de configuração do Termux e vazamento de descritores e processos-zumbi nas sessões de terminal.

## 8.7 Interface

*(Inserir capturas de tela: Dashboard com os Nodes e as barras de CPU/RAM; página do Node com o formulário de criação e os cartões de Workers; terminal com `htop` em execução dentro de um Worker.)*
