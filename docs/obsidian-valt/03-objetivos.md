# 3. Objetivos

## 3.1 Objetivo Geral

Desenvolver e avaliar uma arquitetura de orquestração de ambientes Linux isolados que reaproveite smartphones Android, sem acesso *root*, como nós de um *cluster* de computação de borda, visando uma infraestrutura de servidores de baixo custo alinhada aos princípios da TI Verde.

## 3.2 Objetivos Específicos

- **OE1** — Configurar o ambiente de execução nos dispositivos móveis (Nodes) com o Termux e o `proot-distro`, permitindo executar distribuições Linux (Alpine, Debian e Arch Linux) em espaço de usuário sem privilégios administrativos, de forma automatizada (`setup.sh`). *Responde à QP1.*
- **OE2** — Desenvolver um agente (Node Agent) em Python para coletar métricas de hardware (CPU e memória via `/proc`), descobrir os ambientes instalados, executar as tarefas recebidas e sincronizar seu estado com o servidor orquestrador. *Responde à QP2.*
- **OE3** — Implementar o servidor central (plano de controle) com Flask e Flask-SocketIO, oferecendo um painel web para monitoramento do *cluster* e gerenciamento do ciclo de vida dos Workers (criar, listar, remover). *Responde à QP2.*
- **OE4** — Viabilizar o acesso interativo, em tempo real, à linha de comando dos Workers pelo navegador, integrando WebSockets, pseudo-terminais (PTY) e xterm.js. *Responde à QP2.*
- **OE5** — Avaliar experimentalmente a arquitetura, medindo latência de provisionamento, latência do terminal, sobrecarga do PRoot, disponibilidade dos nós, consumo de energia e temperatura sob cargas leves contínuas. *Responde à QP3 e testa a hipótese H1.*

| Objetivo | Artefato no repositório | Evidência esperada |
|---|---|---|
| OE1 | `android/setup.sh`, `android/run.sh` | Log de instalação; tempo de *setup* |
| OE2 | `android/node.py`, `android/sysinfo.py` | Testes unitários; logs de *sync* |
| OE3 | `desktop/app/routes.py`, `desktop/app/templates/index.html` | Capturas do painel; testes de rota |
| OE4 | `TerminalManager` (`node.py`) + view de terminal | Latência de eco medida |
| OE5 | *(a criar)* scripts de benchmark | Tabelas e gráficos do Cap. 9 |
