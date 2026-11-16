# 7. Metodologia

Este capítulo descreve os procedimentos metodológicos, a arquitetura lógica do sistema e as ferramentas utilizadas no desenvolvimento do protótipo.

## 7.1 Caracterização da Pesquisa

Quanto à natureza, trata-se de **pesquisa aplicada**, pois gera conhecimento para resolver um problema prático: reaproveitar smartphones descartados como infraestrutura computacional. Quanto à abordagem, é **quantitativa**, já que a avaliação se apoia em métricas de desempenho e disponibilidade. Quanto aos procedimentos, segue a **Pesquisa em Ciência do Design** (*Design Science Research* — DSR), em que um artefato é construído para resolver um problema relevante e depois avaliado com rigor (HEVNER et al., 2004; WAZLAWICK, 2014). A avaliação do artefato é **experimental**, em ambiente controlado, conforme as boas práticas de análise de desempenho de sistemas computacionais (JAIN, 1991).

| Etapa da DSR (HEVNER et al., 2004) | Correspondência neste trabalho |
|---|---|
| Identificação do problema | Caps. 1–2 |
| Definição dos objetivos da solução | Cap. 3 |
| Projeto e desenvolvimento do artefato | Caps. 7.2–7.4 e 8 |
| Demonstração | Cap. 8 (cenário de uso) |
| Avaliação | Cap. 9 |
| Comunicação | Artigo e defesa |

## 7.2 Arquitetura Proposta do Sistema

O sistema segue o padrão controlador–trabalhador em três níveis:

- **Plano de controle (Host):** servidor central em Linux (Debian) executando Flask e Flask-SocketIO. Mantém o estado do *cluster* em memória, oferece o painel web ao administrador e enfileira as tarefas de criação e remoção de Workers.
- **Nós (Nodes):** smartphones Android físicos executando, no Termux, o agente `node.py`. Cada Node sincroniza-se com o Host, executa as tarefas recebidas e retransmite as sessões de terminal.
- **Workers:** ambientes Linux (Alpine, Debian ou Arch Linux) criados com `proot-distro` dentro de cada Node e mantidos em execução pelo Supervisor. São os responsáveis pelas cargas de trabalho.

O detalhamento dos componentes, do protocolo e dos fluxos está na nota [08 — Prototipação e implementação](08-prototipacao.md).

## 7.3 Ferramentas e Tecnologias Utilizadas

Priorizou-se software de código aberto, visando baixo custo e reprodutibilidade.

| Tecnologia | Versão mínima | Papel |
|---|---|---|
| Termux (F-Droid) | 0.118 | Ambiente Linux sem *root* no Android |
| `proot-distro` | com suporte a `--isolated` | Provisionamento dos Workers |
| Supervisor | 4.x | Supervisão dos Workers como serviços |
| Python | 3.12 (Host) / versão do Termux (Node) | Linguagem do Host e do agente |
| Flask / Flask-SocketIO | 3.1 / 5.6 | Servidor HTTP e WebSocket do Host |
| python-socketio (cliente) / requests | 5.16 / 2.33 | Comunicação do agente |
| xterm.js + addon-fit | 5.3 / 0.8 | Terminal no navegador |
| Tailwind CSS | (CDN) | Estilo do painel |
| pytest | 9.x | Testes automatizados |
| uv | — | Gerenciamento de dependências |

- **Termux e PRoot:** o Termux fornece o ambiente base no Android; o `proot-distro` instala distribuições completas em espaço de usuário, interceptando chamadas de sistema com `ptrace` (ver [5.4](05-referencial-teorico.md)), sem desbloqueio de *bootloader* nem *root*.
- **Python e Flask:** Python foi escolhido para o Host e para o agente pela biblioteca padrão extensa (`pty`, `subprocess`, `select`) e pela disponibilidade no Termux. O Flask é um *microframework* que facilita a criação de rotas HTTP e da API JSON (GRINBERG, 2018).
- **Comunicação:** o agente usa *polling* HTTP (biblioteca `requests`) a cada 10 s para sincronizar estado e receber tarefas — conexões iniciadas pelo nó são mais robustas diante das restrições de energia e da rede. Para o terminal, usa WebSockets via Socket.IO (Flask-SocketIO no Host, python-socketio no Node), com canal bidirecional de baixa latência.
- **Pseudo-terminais:** o módulo `pty` do Python cria, com `pty.fork()`, um processo-filho que executa `proot-distro login <alias>` ligado a um PTY; uma *thread* lê a saída do lado mestre e a envia ao Host, enquanto as teclas recebidas são escritas no mesmo descritor.
- **Supervisor:** cada Worker vira um programa `[program:<alias>]` com `autorestart=true`, de modo que o ambiente é reiniciado automaticamente se seu processo terminar.

## 7.4 Procedimentos de Implementação

O desenvolvimento seguiu ciclos iterativos e incrementais, registrados no histórico do Git (25 *commits* até a data desta revisão):

1. **Configuração de base:** instalação do Termux e testes do `proot-distro` em AArch64; criação do `setup.sh`, que instala dependências, configura o Supervisor (inclusive o contorno para a ausência de `os.link()` no Python do Termux) e salva a conexão com o Host.
2. **Orquestração HTTP:** criação do painel em Flask e do agente `node.py`, que descobre os Workers lendo o diretório de *rootfs* do `proot-distro` (layouts `installed-rootfs` e `containers`) e sincroniza estado e tarefas por *polling*.
3. **Supervisão e monitoramento:** registro de cada Worker no Supervisor, coleta de CPU e memória via `/proc` (com *fallback* para `top` quando o SELinux bloqueia `/proc/stat`) e relato do resultado de cada tarefa.
4. **Acesso remoto interativo:** integração do xterm.js e retransmissão das sessões PTY por WebSockets, oferecendo ao administrador uma experiência semelhante a uma sessão SSH, mas sem abrir portas no aparelho.
5. **Robustez e testes:** *logs* rotativos nos três componentes, *script* de diagnóstico, reinício automático do agente com espera exponencial (`run.sh`), suporte a início no *boot* (Termux:Boot) e suítes de testes com `pytest` e *mocks*.
