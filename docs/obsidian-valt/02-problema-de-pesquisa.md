# 2. Problema de Pesquisa

Centenas de milhões de smartphones são descartados por ano (SWITZER et al., 2023), embora tenham processadores e memória iguais ou superiores aos das VPS básicas vendidas por provedores de nuvem. Transformá-los em nós de um *cluster*, porém, esbarra no próprio Android.

Cada aplicativo roda em uma *sandbox* com usuário próprio e políticas do SELinux (ANDROID OPEN SOURCE PROJECT, 2024a). Sem *root*, não é possível usar o Docker, que depende de *namespaces* e *cgroups* do *kernel* (MERKEL, 2014; RICE, 2020). Além disso, o sistema interrompe processos em segundo plano. Os modos *Doze* e *App Standby* adiam o acesso à rede e à CPU (ANDROID DEVELOPERS, 2024), o `lmkd` (*Low Memory Killer*) encerra processos para liberar memória (ANDROID OPEN SOURCE PROJECT, 2024b), e, desde o Android 12, o *phantom process killer* mata processos-filho de aplicativos (TERMUX, 2021). Para um servidor, que precisa manter portas abertas o tempo todo, isso significa quedas e perda de estado.

O desafio é de software e de rede: obter comunicação estável e algum isolamento sem alterar o *firmware*, mantendo o baixo custo. A questão central é:

> **Como projetar e orquestrar um *cluster* de smartphones Android reaproveitados, contornando as restrições de privilégio e de gerenciamento de processos do sistema, para provisionar e gerenciar ambientes Linux isolados de forma estável?**

Dela derivam três questões:

- **QP1 — Isolamento:** como provisionar Alpine e Debian no Android sem *root* e qual o custo de desempenho em relação à execução nativa?
- **QP2 — Orquestração e redes:** que combinação de HTTP *polling* e WebSockets mantém Host e Nodes conectados com latência aceitável, tolerando as interrupções do Android?
- **QP3 — Recursos e estabilidade:** como os aparelhos se comportam, em disponibilidade, energia e temperatura, ao sustentar cargas contínuas no PRoot?

## 2.1 Hipótese

**H1:** é possível operar, sem *root*, um *cluster* de smartphones Android que crie ambientes Linux sob demanda e os mantenha disponíveis por longos períodos para cargas leves, desde que (a) a comunicação de controle parta do próprio nó (modelo *pull*), (b) os processos sejam supervisionados e reiniciados automaticamente e (c) as otimizações de bateria do Android estejam desativadas para o Termux.

A hipótese é **confirmada** se os critérios do capítulo 9 forem atendidos, como disponibilidade ≥ 99% em 24 h e latência de terminal p95 ≤ 200 ms em LAN.
