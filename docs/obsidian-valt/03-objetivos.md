# 3. Objetivos

## 3.1 Objetivo Geral

Desenvolver e avaliar uma arquitetura de orquestração de ambientes Linux isolados que reaproveite smartphones Android, sem acesso *root*, como nós de um *cluster* de computação de borda, visando uma infraestrutura de servidores de baixo custo alinhada aos princípios da TI Verde.

## 3.2 Objetivos Específicos

- **OE1** — Configurar de forma automatizada o ambiente dos Nodes com o Termux e o `proot-distro`, para executar Alpine e Debian sem privilégios administrativos. *Responde à QP1.*
- **OE2** — Desenvolver um agente em Python que colete métricas de CPU e memória, descubra os ambientes instalados, execute as tarefas recebidas e sincronize seu estado com o servidor. *Responde à QP2.*
- **OE3** — Implementar o servidor central com Flask e Flask-SocketIO, com um painel web para monitorar o *cluster* e gerenciar o ciclo de vida dos Workers. *Responde à QP2.*
- **OE4** — Oferecer acesso interativo à linha de comando dos Workers pelo navegador, integrando WebSockets, pseudo-terminais (PTY) e xterm.js. *Responde à QP2.*
- **OE5** — Avaliar experimentalmente a arquitetura: tempo de provisionamento, latência do terminal, sobrecarga do PRoot, disponibilidade, energia e temperatura sob cargas leves. *Responde à QP3 e testa a hipótese H1.*
