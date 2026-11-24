# 4. Metodologia

## 4.1 Caracterização da Pesquisa

Trata-se de **pesquisa aplicada**, com abordagem **quantitativa**, conduzida pela **Pesquisa em Ciência do Design** (*Design Science Research*), em que um artefato é construído para resolver um problema relevante e depois avaliado com rigor (Hevner *et al.*, 2004; Wazlawick, 2014). O problema e os objetivos estão na seção 1, o artefato na seção 5 e a avaliação, **experimental** e em ambiente controlado (Jain, 1991), na seção 6.

## 4.2 Arquitetura Proposta do Sistema

O sistema segue o padrão controlador–trabalhador em três níveis:

- **Host (plano de controle):** servidor Linux com Flask e Flask-SocketIO. Guarda o estado dos Nodes, oferece o painel web e enfileira as tarefas de criar e remover Workers.
- **Nodes:** smartphones Android que rodam, no Termux, o agente `node.py`. Cada Node se sincroniza com o Host, executa as tarefas e retransmite as sessões de terminal.
- **Workers:** ambientes Linux (Alpine ou Debian) criados com `proot-distro` dentro de cada Node e mantidos em execução pelo Supervisor. São eles que rodam as cargas.

## 4.3 Ferramentas e Tecnologias Utilizadas

Só foi usado software de código aberto. Nos Nodes, o Termux (F-Droid, 0.118), o `proot-distro` 5.10 e o Supervisor 4.3. No Host, Python, Flask 3.1 e Flask-SocketIO 5.6 (Grinberg, 2018). No agente, `requests` e python-socketio. No painel, xterm.js. Os testes usam pytest, e os experimentos, *scripts* em Python, SSH para o Termux e o gerador de carga HTTP `hey`. O agente sincroniza por *polling* HTTP a cada 10 s, porque conexões que partem do aparelho resistem melhor às restrições de energia e de rede, e usa WebSocket só para o terminal. O terminal é um processo `proot-distro login <alias>` ligado a um PTY pelo módulo `pty` do Python.

## 4.4 Procedimentos de Implementação

O desenvolvimento foi iterativo e ficou registrado no Git, em cinco etapas: (1) base no Termux e o `setup.sh`, que instala dependências e configura o Supervisor; (2) painel em Flask e agente sincronizando estado e tarefas por *polling*; (3) supervisão dos Workers e coleta de CPU e memória pelo `/proc`; (4) terminal no navegador por WebSocket, sem abrir portas no aparelho; (5) robustez: *logs* rotativos, reinício automático do agente, início no *boot* e testes automatizados com `pytest`.
