# DroidServer

Transforme smartphones Android antigos — **sem root** — em nós de um pequeno cluster de servidores Linux.

Um servidor **Host** (Flask + Socket.IO) controla vários **Nodes** Android. Em cada Node, um agente Python rodando no [Termux](https://termux.dev/) cria ambientes Linux com `proot-distro` (Alpine, recomendado, ou Debian), chamados **Workers**, e os mantém de pé com o **Supervisor**. Tudo é operado por um painel web com métricas em tempo real e terminal interativo no navegador.

> Projeto de TCC em Engenharia da Computação (Uninorte, Manaus — 2026): **"DroidServer: gerenciamento de ambientes Linux do tipo VPS em smartphones Android reaproveitados sem acesso root"**. A documentação acadêmica está em [`docs/obsidian-valt/`](docs/obsidian-valt/README.md); o que já foi feito está em [`docs/HISTORICO.md`](docs/HISTORICO.md) e o que falta, em [`docs/PROXIMOS-PASSOS.md`](docs/PROXIMOS-PASSOS.md).

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
| **Worker** | Um serviço dentro de um Node, registrado no Supervisor. Há dois tipos: **ambiente Linux** (container `proot-distro` com o `/app/run.sh`) e **banco PostgreSQL** (instância nativa do Termux, sem container) |
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

### Cadastro dos Nodes (pareamento pelo painel)

O celular **não precisa saber o IP do Host**. O agente abre a porta **5051**, que só responde a duas coisas: "quem é você?" (`GET /droidserver`) e "pareie comigo" (`POST /parear`).

1. No Dashboard, **Adicionar node** → informe o IP do celular ou clique em **Varrer**. A varredura pergunta a cada endereço da rede (por padrão, a `/24` do Host) se há um agente na porta 5051, e lista modelo, versão do Android e se ele já está pareado.
2. Ao adicionar, o Host gera um **token exclusivo** para aquele Node e o envia junto com a própria porta. O Node usa como endereço do Host o IP de quem fez o pedido e salva tudo em `~/.config/droidserver/pareamento.json` (modo 600).
3. A partir daí, o Node sincroniza como descrito abaixo, e o Host **só aceita syncs de Nodes cadastrados**, com o token certo. O cadastro fica em `desktop/data/nodes.json` e sobrevive a reinícios do Host.

O Node é identificado pelo **token**, não pelo IP: se o celular voltar de um reboot com outro IP (DHCP), o Host move o cadastro, o estado e o histórico para o IP novo. Um Node pareado por um painel só aceita novo pareamento vindo do mesmo Host; **Remover** no card do Node desfaz o pareamento no celular.

Depois do pareamento, toda conexão de operação é **iniciada pelo Node** (sync e WebSocket do terminal), o que tolera as restrições de energia do Android.

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
3. O Node limpa resíduos do mesmo alias, roda `proot-distro install <distro> --override-alias <alias>`, grava o **lançador** do serviço no container, cria `$PREFIX/etc/supervisor/conf.d/<alias>.conf` e recarrega o Supervisor.
4. O Supervisor roda `proot-distro login [--isolated] <alias> -- /bin/sh /app/.droidserver/lancador.sh`, com limites `ulimit` (arquivos abertos e processos).
5. O Worker fica em **"Aguardando run.sh"** até você escrever o serviço na aba **Serviço** (veja abaixo).
6. O resultado (✓/✗) aparece no painel no sync seguinte.

### Serviço do Worker (`/app/run.sh`)

Cada Worker tem **um serviço: o arquivo `/app/run.sh`** dentro do container. O Supervisor não o executa diretamente, e sim um lançador (`/app/.droidserver/lancador.sh`) que **espera o `run.sh` existir** e então o executa em primeiro plano. Basta criar o arquivo para o serviço subir.

Na página do Worker, aba **Serviço**:

| O quê | Como |
|---|---|
| **O que roda** | Editor do `/app/run.sh` (com "Inserir exemplo"; `Ctrl+S` salva). "Salvar e reiniciar" aplica na hora |
| **Controle** | Iniciar · Parar · Reiniciar, com estado, pid e tempo no ar |
| **Visão geral** | Endereço `http://<ip>:<porta>` com **Abrir** e **Testar** (o Host acessa o serviço e mostra o código HTTP e o tempo), falhas do dia com a causa da última (ex.: "comando não encontrado (127)", lida do log do supervisord), CPU, RAM do serviço, disco do Worker (calculado em segundo plano), distribuição e quando o `run.sh` foi salvo |
| **Quando** | "Iniciar junto com o celular" (`autostart`) e "Reiniciar automaticamente se cair" (`autorestart`); valem a partir da próxima reinicialização do serviço |
| **Logs** | Saída e erros ao vivo (últimas 200 linhas ao abrir), com pausar, limpar e baixar |
| **Ajuda** | Botões **?** abrem um guia lateral: passo a passo, regras do `run.sh`, porta, exemplos (site estático, API Python, Node.js, bot), estados, erros comuns e opções. Avisos de `&`/`nohup` e explicação quando o serviço falha logo ao iniciar |

Regras do `run.sh`: o serviço precisa ficar em **primeiro plano**, use `exec` no último comando e lembre que a rede não é isolada (a porta aberta fica em `http://<ip-do-celular>:<porta>`; dois Workers não podem usar a mesma). Exemplo:

```sh
#!/bin/sh
# droidserver: porta=8080
cd /app
exec python3 -m http.server 8080
```

A linha `# droidserver: porta=8080` informa ao painel em que porta o serviço escuta (o Android não permite descobrir isso sem *root*: `/proc/net/tcp` é negado). Sem ela, a visão geral mostra "Porta não informada".

O *shebang* é respeitado: um `run.sh` com `#!/bin/bash` ou `#!/usr/bin/env python3` roda com esse interpretador (instale-o antes; o Alpine só traz o `sh`). Sem *shebang*, o arquivo roda com `sh`. Por segurança, `/app/run.sh` não pode ser um link simbólico.

Os comandos e os logs passam pelo WebSocket já aberto entre o Host e o Node (resposta imediata, sem esperar o sync), e os logs vão só para o navegador que está com a aba aberta. Workers criados por versões anteriores são migrados ao iniciar o agente: um `/app/run_server.sh` próprio vira `/app/run.sh`.

### Cloudflare Tunnel (fora do escopo do TCC)

Cada Node pode ter um tunnel da Cloudflare para publicar os Workers na Internet sem abrir portas no roteador. O `cloudflared` roda **no Termux, fora do proot**, como um programa do Supervisor com o nome reservado `tunnel` (nenhum Worker pode se chamar assim).

1. Na Cloudflare, em **Zero Trust → Networks → Tunnels**, crie um tunnel do tipo `cloudflared` e copie o token. Pode copiar o comando inteiro (`cloudflared tunnel run --token …`); o painel extrai o token.
2. Na página do Node, cole o token no card **Tunnel Cloudflare**. O agente instala o `cloudflared` com `pkg install` se faltar, grava o token em `~/.config/droidserver/tunnel.env` (0600) e sobe `cloudflared tunnel --no-autoupdate run`.
3. Em **Public Hostnames**, aponte cada hostname para `http://localhost:<porta do Worker>`.

A tela **Abrir tunnel** (`/node/<ip>/tunnel`) tem Iniciar/Parar/Reiniciar, as opções de inicialização, a troca de token, a remoção e o log do `cloudflared` ao vivo, pelos mesmos eventos da aba Serviço com `alias: "tunnel"`. O token não aparece no `ps` nem no `.conf`, porque o `cloudflared` o lê da variável `TUNNEL_TOKEN`. Ele também não é gravado no Host: fica só na fila em memória até o Node buscá-lo, e o painel mostra apenas os últimos 4 caracteres. Se a tarefa se perder no caminho, o painel avisa para enviar de novo.

### Workers de banco: PostgreSQL (fora do escopo do TCC)

No formulário **Criar novo worker**, o tipo **Banco PostgreSQL** cria uma instância do PostgreSQL pronta para receber conexões pela rede, sem escrever `run.sh`:

1. O Host gera uma senha aleatória e enfileira `criar_worker` com `tipo: "postgres"`. A senha só aparece no painel como `…xxxx` e nos logs também.
2. O agente instala o pacote `postgresql` do Termux se faltar (~30 MB), roda o `initdb` com o usuário `droidserver` (senha lida de um arquivo 0600 apagado em seguida), libera a rede com `scram-sha-256` e limita a memória (`shared_buffers=16MB`, `max_connections=20`).
3. A porta é 5432, ou a próxima livre se já houver outra instância ou outro serviço nela.
4. O Supervisor roda `postgres -D <dados>` com o alias do Worker e para com `SIGINT` (parada rápida). Dados e configuração ficam em `~/.local/share/droidserver/bancos/<alias>/`.

Na aba **Serviço**, o editor do `run.sh` dá lugar ao card **Conexão** (host, porta, usuário, banco e senha). **Mostrar senha** e **Copiar URL** (`postgresql://droidserver:<senha>@<ip>:5432/postgres`) pedem a senha ao Node na hora, pela ação `credenciais`, que responde só ao navegador que pediu. Ela nunca vem no sync. **Testar** abre uma conexão TCP na porta. A aba **Terminal** abre o `psql` já conectado. Iniciar/Parar/Reiniciar, opções, logs, falhas do dia, CPU, RAM e disco funcionam como nos outros Workers.

#### Vários bancos numa instância

Cada instância custa ~70 MB de RAM, então o caminho preferido para várias aplicações é **uma instância com vários bancos**. No card Conexão, **Novo banco** pede um nome (minúsculas, dígitos e `_`) e o Node cria, pelo `psql` local, um usuário e um banco com esse nome, com senha própria gerada no celular. O `CONNECT` do banco é revogado de `PUBLIC`, então só o dono e o `droidserver` entram nele. O seletor **Banco** troca usuário, senha, URL e os comandos de migração do card. **Apagar banco** pede para digitar o nome de novo e roda `DROP DATABASE … WITH (FORCE)` e `DROP ROLE`. As senhas ficam no `banco.json` (0600) e, como a do admin, só saem pela ação `credenciais`. Os nomes vão para o `psql` por `\set` no stdin (citados com `:"nome"`/`:'senha'`), nunca no argv nem montados no SQL. A instância precisa estar rodando. Bancos criados à mão pelo `psql` funcionam, mas não aparecem na lista.

Também dá para ter várias instâncias, uma por worker (portas 5432, 5433…), quando for preciso isolar de verdade (versões de configuração, reinícios independentes).

#### Versão do PostgreSQL

Não dá para escolher a versão: o Termux empacota uma só (a atual do repositório), e outras versões no proot esbarram no mesmo travamento do `initdb`. O risco real é o `pkg upgrade` do `setup.sh` trocar a versão **major** e deixar os dados antigos sem subir. Por isso o agente roda `apt-mark hold postgresql` ao instalar o pacote ou criar uma instância. O custo é que as atualizações *minor* (correções) também ficam presas até você liberar à mão.

Se a major dos dados (`dados/PG_VERSION`) não bater com a do binário, a Visão geral mostra o aviso **Versão incompatível**, e Iniciar/Reiniciar e a criação de bancos são recusados (sem isso, o Supervisor ficaria reiniciando em loop).

**Atualizar a versão do PostgreSQL** (planejado, com os dados):

1. Com a instância ainda na versão antiga, faça o backup pelo seu computador, com os comandos do bloco **Migrar dados** (banco *admin*: `pg_dumpall -d "<url>" -f instancia.sql`).
2. No Termux: `apt-mark unhold postgresql && pkg upgrade postgresql && apt-mark hold postgresql`.
3. Crie um worker de banco novo (e apague o antigo depois de conferir).
4. Restaure: `psql -d "<url do novo>" -f instancia.sql`.

#### Migrar dados

A porta do worker aceita conexões da rede, então a migração usa as ferramentas do próprio PostgreSQL rodando no seu computador. O bloco **Migrar dados** do card Conexão traz os comandos prontos, com a URL do banco selecionado (a senha entra depois de **Mostrar senha**):

| Para | Comando |
|---|---|
| Importar de outro servidor | `pg_dump --no-owner --no-acl "<origem>" \| psql "<destino>"` |
| Fazer backup | `pg_dump -Fc "<destino>" -f banco.dump` |
| Restaurar um backup | `pg_restore --no-owner --no-acl -d "<destino>" banco.dump` |
| Instância inteira (admin) | `pg_dumpall -d "<destino>" -f instancia.sql` e, na nova, `psql -d "<destino>" -f instancia.sql` |

O `pg_dump` precisa ser da mesma versão do servidor de origem ou mais novo. `--no-owner --no-acl` faz os objetos ficarem com o dono do banco de destino.

**Por que fora do proot:** o PostgreSQL precisa de memória compartilhada System V, e a emulação do proot (`--sysvipc`) trava quando o `postgres` roda pela segunda vez na mesma sessão. O `initdb` faz isso várias vezes, então nunca termina (testado no moto e40 com Debian 13 e PostgreSQL 17; o defeito é do proot, não da distribuição). O pacote do Termux usa a `libandroid-shmem` e roda direto: `initdb` em ~3 s e cerca de 70 MB de RAM parado por instância (soma dos processos do PostgreSQL, como o painel mostra).

### Terminal (WebSocket)

```
xterm.js ─terminal_input─► Host ─cmd_to_<ip>_<alias>─► Node ─► PTY (proot-distro login)
xterm.js ◄output_for_<ip>_<alias>─ Host ◄terminal_output─ Node ◄─┘
```

O agente abre o WebSocket com `auth={papel: "node", ip, token}`; o Host só manda comandos (terminal, serviço, logs) a sockets autenticados assim, e só aceita deles a saída do terminal, os logs e as respostas. A saída de cada terminal vai apenas para quem o abriu (sala `term:<ip>:<alias>`, via `terminal_assinar`).

O PTY é aberto na primeira tecla recebida, e o redimensionamento da janela é repassado via `terminal_resize` → `resize_to_<ip>_<alias>` (`TIOCSWINSZ`).

### Arquivos do Worker (aba Arquivos)

Ao lado do Terminal, a aba **Arquivos** navega pela pasta home do Worker (`/root`, a mesma em que o terminal abre) e permite **enviar** arquivos ou pastas inteiras (botões ou arrastar e soltar), **baixar** um arquivo ou uma pasta (em `.zip`), **criar pasta** e **apagar** arquivo ou pasta.

```
Navegador ─/api/node/<ip>/worker/<alias>/arquivos/*─► Host ─/arquivos/* + X-Droid-Token─► Node (porta 5051) ─► rootfs/root
```

O Host repassa cada requisição ao Node em blocos (nada é guardado inteiro na memória) com o token do pareamento; o Node só atende o Host pareado (mesmo IP e token) e lê/grava direto no rootfs, sem abrir sessão do proot (`android/arquivos.py`). Caminhos com `..` e links simbólicos que saem de `/root` são recusados (aparecem na lista, mas não são seguidos nem entram no `.zip`); um envio só substitui o arquivo quando termina (grava num temporário e troca). Workers de banco não têm a aba Arquivos (o terminal deles é o `psql`), e o Host recusa essas rotas para eles.

## Estrutura do projeto

```
DroidServer/
├── android/                  # Agente do Node (roda no Termux)
│   ├── node.py               # NodeAgent, WorkerManager, TerminalManager
│   ├── servico.py            # Serviço do Worker (/app/run.sh, lançador, .conf do Supervisor)
│   ├── arquivos.py           # Aba Arquivos: listar, enviar, baixar (.zip) e apagar na home do Worker
│   ├── banco.py              # Workers de banco: PostgreSQL nativo do Termux
│   ├── tunnel.py             # Cloudflare Tunnel (cloudflared no Termux)
│   ├── registro.py           # Registro local de métricas e disponibilidade
│   ├── sysinfo.py            # CPU/memória via /proc (fallback: top)
│   ├── setup.sh              # Primeiro uso: pacotes, Supervisor, conexão, boot
│   ├── run.sh                # Inicia/para o agente (primeiro ou segundo plano)
│   ├── diagnostico.sh        # Coleta informações para depuração
│   ├── tests/                # Testes com mocks (rodam fora do Android)
│   └── pyproject.toml
├── desktop/                  # Host (plano de controle)
│   ├── main.py               # Ponto de entrada — porta 5050
│   ├── app/
│   │   ├── __init__.py       # create_app, Socket.IO e logs
│   │   ├── routes.py         # Páginas, API REST e eventos Socket.IO
│   │   ├── static/vendor/    # Tailwind, xterm.js, Socket.IO e fonte (painel sem internet)
│   │   └── templates/        # index.html (SPA), login.html, apresentacao.html
│   ├── tests/test_routes.py
│   ├── Dockerfile, docker-compose.yml
│   └── pyproject.toml
├── bench/                    # Experimentos do TCC (E1–E10), resultados em CSV e gráficos
└── docs/
    ├── obsidian-valt/        # Texto do TCC (Obsidian) — fonte única
    ├── gerador-docx/         # Gera o .docx ABNT a partir do vault
    ├── DroidServer_TCC_artigo.docx      # artigo base do TCC (com capa e folha de rosto)
    ├── DroidServer_artigo_topicos.docx  # mesmo artigo, no formato da Revista Tópicos
    ├── HISTORICO.md          # O que já foi feito
    └── PROXIMOS-PASSOS.md    # O que falta fazer
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
DROID_PANEL_PASSWORD='escolha-uma-senha' uv run python main.py
```

O painel fica em `http://<ip-do-host>:5050` e pede a senha definida em `DROID_PANEL_PASSWORD` (sem ela, o painel fica aberto a quem estiver na rede). Libere a porta 5050 no firewall, se houver. O painel funciona sem internet.

**Com Docker** (opcional, Linux): sobe o painel sem instalar Python nem `uv`.

```bash
cd desktop
cp .env.example .env   # e troque a senha em DROID_PANEL_PASSWORD
docker compose up -d --build
```

O container usa a rede do host (`network_mode: host`), porque o painel precisa enxergar o IP real da LAN para sugerir a rede da varredura e alcançar os Nodes na porta 5051. O cadastro dos Nodes e a chave da sessão ficam no volume `droid-data`, e os logs em `droid-logs` (`docker compose logs -f` mostra a saída). Para parar: `docker compose down`.

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
4. mostra o IP do celular — não é preciso informar nada sobre o Host;
5. opcionalmente cria um container Alpine de teste e configura o início automático com o Termux:Boot.

Depois, inicie o agente e **adicione o celular pelo painel** (Dashboard → Adicionar node → IP ou Varrer):

```bash
bash android/run.sh -d
```

| Comando | Efeito |
|---|---|
| `bash android/run.sh` | Primeiro plano (Ctrl+C encerra) |
| `bash android/run.sh -d` | Segundo plano, com `termux-wake-lock` e reinício automático |
| `bash android/run.sh status` | Mostra se o agente está rodando |
| `bash android/run.sh stop` | Encerra o agente em segundo plano |

O `run.sh` garante que o `supervisord` esteja de pé e reinicia o agente se ele cair (espera exponencial de 2 s a 60 s).

### O painel pode ser desligado

Tudo o que roda e tudo o que é registrado fica no celular; o painel (Host) serve só para configurar, monitorar e gerenciar e pode ser desligado a qualquer momento. Sem ele, os serviços continuam sob o Supervisor e o agente continua medindo. A cada 10 s, com ou sem painel (e mesmo antes do pareamento), o agente grava em `~/.config/droidserver/registro/metricas.jsonl` (JSON Lines, 2 MB × 10 arquivos, cerca de uma semana):

- CPU do DroidServer, RAM do aparelho e memória (RSS) do agente e do `supervisord`;
- para cada serviço: estado no Supervisor, pid, tempo no ar, CPU, RAM e um `GET` local na porta declarada no `run.sh` (`http_ok`, status, tempo de resposta);
- se o painel estava acessível naquele ciclo.

Os logs dos serviços (`$PREFIX/var/log/droidserver_<worker>.log`), do Supervisor e do agente (`~/.config/droidserver/logs/node.log`) também ficam no celular. Quando o painel cai, o agente registra um aviso só na queda e outro na volta. Ao ser ligado de novo, o painel pede a cada Node os últimos 30 minutos do registro, e o gráfico volta completo.

### Mantendo o Node vivo

O Android encerra processos em segundo plano agressivamente. Para um Node estável:

- desative a otimização de bateria do Termux (*Configurações → Apps → Termux → Bateria → Sem restrições*);
- use `run.sh -d`, que ativa o `termux-wake-lock`;
- **Android 12 ou superior:** desative o *phantom process killer* (nas opções de desenvolvedor, "Desativar restrições de processos filhos", ou via ADB), senão o Termux pode ser encerrado com `signal 9`. Veja [termux-app#2366](https://github.com/termux/termux-app/issues/2366).

## Uso

1. Acesse `http://<host>:5050`. O **Dashboard** mostra os Nodes, se estão online e o uso de CPU/RAM de cada um.
2. Clique em **Gerenciar Workers** para abrir a página do Node.
3. Escolha a distribuição (**Alpine**, recomendada: ~50 MB e pronta em segundos; ou **Debian**, ~150 MB, quando o software exigir glibc/`apt`), informe um alias (`[A-Za-z0-9_-]`, até 64 caracteres) e clique em **Criar Container**. A opção **Isolar do host** (`--isolated`, ativada por padrão) impede o Worker de enxergar o *home* do Termux e o armazenamento do aparelho.
4. Acompanhe "Em processamento" e "Últimas operações"; o Worker aparece como **Aguardando run.sh**.
5. Clique em **Serviço**: escreva o `/app/run.sh` e use **Salvar e reiniciar**. Instale o que o serviço precisa pelo **Terminal** (ícone ao lado; ex.: `apk add python3`).
6. Acompanhe os logs na mesma aba. O ícone de lixeira remove o Worker.

## Configuração

### Variáveis de ambiente

| Variável | Onde | Padrão | Descrição |
|---|---|---|---|
| `DROID_NODE_PORT` | Node | `5051` | Porta de descoberta e pareamento do agente |
| `DROID_PAREAMENTO_FILE` | Node | `~/.config/droidserver/pareamento.json` | Onde o pareamento feito pelo painel é salvo |
| `DROID_HOST_IP` / `DROID_HOST_PORT` / `DROID_TOKEN` | Node | vazio | Modo antigo (manual), usado só se não houver pareamento; o Host exige cadastro, então é preciso adicionar o Node pelo painel de qualquer forma |
| `DROID_LOG_FILE` | Node | `~/.config/droidserver/logs/node.log` | Arquivo de log do agente |
| `DROID_ULIMIT_NOFILE` | Node | `4096` | Limite de arquivos abertos por Worker (`0` desativa) |
| `DROID_ULIMIT_NPROC` | Node | `1024` | Limite de processos por Worker (`0` desativa) |
| `DROID_BANCOS_DIR` | Node | `~/.local/share/droidserver/bancos` | Dados e configuração dos Workers de banco |
| `DROID_PG_SHARED_BUFFERS` / `DROID_PG_MAX_CONNECTIONS` | Node | `16MB` / `20` | Memória e conexões de cada PostgreSQL criado (valem para as próximas instâncias) |
| `DROID_DATA_DIR` | Host | `desktop/data/` | Onde fica o cadastro de Nodes (`nodes.json`, com os tokens) |
| `DROID_NODE_PORT` | Host | `5051` | Porta usada para sondar e parear os Nodes |
| `DROID_BIND` | Host | `0.0.0.0` | Endereço em que o Host escuta |
| `DROID_PORT` | Host | `5050` | Porta do Host |
| `DROID_DEBUG` | Host | `0` | `1` liga o modo debug — só aceito com `DROID_BIND=127.0.0.1` |
| `DROID_PANEL_PASSWORD` | Host | vazio | **Senha do painel.** Definida, o painel e o WebSocket dos navegadores exigem login (sessão de 12 h); vazia, o painel fica aberto (aviso no log) |
| `DROID_SECRET_KEY` | Host | gerada em `data/secret_key` | Chave que assina o cookie de login (persistente: reiniciar o Host não derruba o login) |
| `DROID_CORS_ORIGINS` | Host | mesma origem | Origens extras aceitas no WebSocket, separadas por vírgula (ex.: painel atrás de proxy HTTPS) |
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
| `POST` | `/api/node_sync` | Sync do Node (exige o token do cadastro); responde `{"status": "ok", "tarefas": [...]}` ou 401 |
| `GET` | `/api/node/<ip>/historico` | Série de CPU do DroidServer e RAM (até 30 min) para o gráfico |
| `GET` | `/api/rede` | Rede sugerida para a varredura (a `/24` do Host) |
| `POST` | `/api/varredura` | `{"rede": "192.168.1.0/24"}` → Nodes que respondem na porta 5051 (no máximo uma `/22`) |
| `POST` | `/api/nodes/adicionar` | `{"ip": "..."}` → pareia o Node e o cadastra |
| `POST` | `/api/nodes/<ip>/remover` | Remove do cadastro e desfaz o pareamento no celular |

| `POST` | `/deploy_worker` | Form `ip`, `alias`, `tipo` (`linux` ou `postgres`), `imagem`, `isolado` → enfileira `criar_worker` (com `tipo: "postgres"` e a senha gerada, no caso do banco) |
| `POST` | `/api/node/<ip>/worker/<alias>/testar` | Testa o serviço a partir do Host: HTTP na porta do `run.sh`, ou TCP no caso do banco |
| `POST` | `/node/<ip>/worker/<alias>/delete` | Enfileira `deletar_worker` (GET responde 405) |
| `GET` | `/api/node/<ip>/worker/<alias>/arquivos?caminho=` | Lista a pasta (relativa a `/root`): `{itens: [{nome, tipo, tamanho, modificado, link}]}` |
| `GET` | `/api/node/<ip>/worker/<alias>/arquivos/baixar?caminho=` | Baixa o arquivo, ou a pasta como `.zip` |
| `POST` | `/api/node/<ip>/worker/<alias>/arquivos/enviar?caminho=` | Corpo = conteúdo do arquivo; cria as pastas que faltarem e substitui o existente |
| `POST` | `/api/node/<ip>/worker/<alias>/arquivos/pasta?caminho=` | Cria a pasta |
| `POST` | `/api/node/<ip>/worker/<alias>/arquivos/apagar?caminho=` | Apaga o arquivo ou a pasta inteira (a home não pode ser apagada) |
| `GET` | `/node/<ip>/tunnel` | SPA: tela do Cloudflare Tunnel |
| `POST` | `/node/<ip>/tunnel` | `{"token": "..."}` (ou o comando com `--token`) → enfileira `configurar_tunnel`; responde `{ok, token_fim}` |
| `POST` | `/node/<ip>/tunnel/delete` | Enfileira `remover_tunnel` |
| `GET`/`POST` | `/login` | Login do painel (só com `DROID_PANEL_PASSWORD`) |
| `POST` | `/logout` | Encerra a sessão |

Com senha definida, as rotas acima exigem login (páginas redirecionam para `/login`; a API responde 401), exceto `/api/node_sync`, autenticada pelo token do Node. Todo `POST` vindo de **outro site** (cabeçalho `Origin` diferente do painel) é recusado com 403.

No Node (porta 5051): `GET /droidserver` (identificação), `POST /parear` (`{host_port, token, token_atual?}`; `token_atual` permite ao mesmo Host parear de um IP novo) e `POST /desparear` (`{token}`, só do Host pareado). Também na 5051, só para o Host pareado (mesmo IP e cabeçalho `X-Droid-Token`): `GET /arquivos/listar`, `GET /arquivos/baixar`, `POST /arquivos/enviar`, `POST /arquivos/pasta` e `POST /arquivos/apagar`, todos com `?alias=&caminho=`.

### Socket.IO

| Evento | Direção | Payload |
|---|---|---|
| `node_updated` | Host → painéis | `{ip}` — o painel recarrega os dados |
| `connect` (auth) | Node → Host | `{papel: "node", ip, token}` — identifica o socket do Node; sem isso é um navegador (que precisa de login, se houver senha) |
| `terminal_assinar` / `terminal_cancelar` | Navegador → Host | `{ip, alias}` (entra/sai da sala `term:<ip>:<alias>`) |
| `terminal_input` | Navegador → Host | `{ip, alias, input}` |
| `terminal_resize` | Navegador → Host | `{ip, alias, cols, rows}` |
| `terminal_output` | Node → Host | `{ip, alias, output}` |
| `cmd_to_<ip>_<alias>` | Host → Node | `{input}` |
| `resize_to_<ip>_<alias>` | Host → Node | `{cols, rows}` |
| `output_for_<ip>_<alias>` | Host → sala do terminal | `{output}` |
| `servico` | Navegador → Host | `{ip, alias, acao, dados, req}` — `acao`: iniciar, parar, reiniciar, ler_script, salvar_script, configurar, exemplo; só banco: credenciais (`dados.banco` opcional), criar_banco e apagar_banco (`dados.nome`) |
| `servico_to_<ip>` | Host → Node | `{alias, acao, dados, sid, req}` |
| `servico_resposta` | Node → Host → navegador que pediu | `{alias, acao, req, ok, msg, dados, servico}` |
| `logs_assinar` / `logs_cancelar` | Navegador → Host | `{ip, alias}` (entra/sai da sala `logs:<ip>:<alias>`) |
| `logs_to_<ip>` | Host → Node | `{alias, acao: assinar\|cancelar}` — o node só lê o log enquanto alguém assiste |
| `logs_saida` | Node → Host → sala do Worker | `{alias, linhas, inicial}` |

## Logs e diagnóstico

| Componente | Local |
|---|---|
| Setup | `~/.config/droidserver/logs/setup-<data>.log` (um por execução) |
| Agente | `~/.config/droidserver/logs/node.log` (rotativo, 2 MB × 5) |
| Agente em segundo plano (stdout) | `~/.config/droidserver/logs/agent.out` |
| Supervisor | `$PREFIX/var/log/supervisor/supervisord.log` |
| Serviço de cada Worker | `$PREFIX/var/log/droidserver_<alias>.log` (saída e erros juntos; rotação 1 MB × 3) — também na aba Serviço |
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

São 312 testes (106 no Host e 206 no agente), incluindo testes de regressão para a perda de resultados no sync, o uso do `supervisord.conf` correto e o fechamento das sessões de PTY.

## Segurança e limitações

O DroidServer é um protótipo acadêmico para uso **em rede local confiável**:

- defina **`DROID_PANEL_PASSWORD`**: sem ela, o painel fica aberto a quem alcançar a porta (o Host avisa no log). Com ela, páginas, API e WebSocket dos navegadores exigem login; os Nodes continuam autenticados pelo token;
- POSTs de outros sites são recusados (verificação do `Origin`) e o WebSocket só aceita a origem do próprio painel; comandos e saídas de terminal circulam só entre o Node autenticado e quem abriu o terminal;
- não há TLS: a senha e os tokens trafegam em texto claro na rede local. Para uso fora de uma LAN confiável, coloque o Host atrás de um proxy HTTPS;
- um Node **ainda não pareado** aceita o pareamento de qualquer máquina da rede (depois de pareado, só do mesmo Host ou de quem provar o token atual); o modo debug fica desligado por padrão e só pode ser ligado escutando em `127.0.0.1`;
- o painel não depende de internet: Tailwind, xterm.js, Socket.IO e a fonte são servidos pelo Host (`desktop/app/static/vendor/`);
- o PRoot isola apenas o sistema de arquivos: Workers compartilham rede, processos, CPU e memória com o aparelho (sem `cgroups`), e o `ptrace` adiciona sobrecarga em operações de E/S;
- o cadastro de Nodes é persistido no Host; o estado de operação (workers, métricas) é refeito pelos syncs em até 10 s após reiniciar o Host, e o histórico do gráfico é recarregado do registro de cada celular.

## Licença

Código sob a licença MIT (ver [LICENSE](LICENSE)).
