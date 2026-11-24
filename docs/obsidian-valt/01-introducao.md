# 1. Introdução

## 1.1 Contextualização

A demanda por mais desempenho e as práticas de obsolescência programada e percebida (Slade, 2006) fazem crescer o lixo eletrônico (*e-waste*). Em 2022, o mundo gerou 62 milhões de toneladas de resíduos eletroeletrônicos, 82% a mais que em 2010, e só 22,3% foram coletados e reciclados de forma adequada (Baldé *et al.*, 2024). Cerca de 1,5 bilhão de smartphones são vendidos por ano, e a maioria é descartada em menos de dois anos (Switzer *et al.*, 2023).

Muitos desses aparelhos saem de uso por falhas periféricas, como tela quebrada, bateria gasta ou fim das atualizações, enquanto o processador ARM *multicore*, a memória e o armazenamento continuam funcionando. Mesmo aparelhos antigos têm capacidade compatível com microsserviços modernos (Switzer *et al.*, 2023), e como a energia de fabricação domina o consumo ao longo da vida útil, reaproveitá-los é vantajoso (Shahrad; Wentzlaff, 2017). A Computação de Borda (*Edge Computing*), que leva o processamento para perto de onde os dados são gerados (Satyanarayanan, 2017; Shi *et al.*, 2016), é um destino natural para esse recurso ocioso.

Este trabalho apresenta o **DroidServer**, um protótipo que gerencia uma pequena frota de smartphones Android sem acesso *root* a partir de um servidor central. Cada aparelho roda um agente em Python no Termux, que cria ambientes Linux com o `proot-distro`, mantém esses ambientes como serviços supervisionados e envia métricas ao servidor. O administrador opera tudo por um painel web, que inclui um terminal no navegador. O sistema **não** tem escalonador: quem escolhe o aparelho de cada ambiente é o administrador, e por isso o trabalho fala em gerenciamento, e não em orquestração.

Aqui, **servidor virtual privado** (VPS) designa o **modelo de serviço** que cada Worker oferece: um ambiente Linux próprio, com arquivos, pacotes e serviços independentes, acessível pela rede e administrado como um servidor. Não há virtualização de *hardware* nem isolamento pelo *kernel*. Os Workers compartilham o *kernel*, a rede, a CPU e a memória do aparelho, e o isolamento se limita ao sistema de arquivos, obtido pelo PRoot (seção 2.4). Os custos dessa escolha são medidos na seção 6.

Ao longo do texto, **Host** é o computador que executa o servidor central (plano de controle); **Node** é um smartphone Android que executa o agente; e **Worker** é um ambiente Linux criado com o `proot-distro` dentro de um Node.

## 1.2 Problema, questões de pesquisa e hipótese

Transformar smartphones descartados em servidores esbarra no próprio Android. Cada aplicativo roda em uma *sandbox* com usuário próprio e políticas do SELinux (Android Open Source Project, 2024a). Sem *root*, não é possível usar o Docker, que depende de *namespaces* e *cgroups* do *kernel* (Merkel, 2014; Rice, 2020). Além disso, o sistema interrompe processos em segundo plano: os modos *Doze* e *App Standby* adiam o acesso à rede e à CPU (Android Developers, 2024), o `lmkd` (*Low Memory Killer*) encerra processos para liberar memória (Android Open Source Project, 2024b) e, desde o Android 12, o *phantom process killer* mata processos-filho de aplicativos (Termux, 2021). Para um servidor, que precisa manter portas abertas o tempo todo, isso significa quedas e perda de estado. O desafio, portanto, é de software e de rede: obter comunicação estável e algum isolamento sem alterar o *firmware*. Dele derivam três questões:

- **QP1 — Isolamento:** como provisionar Alpine e Debian no Android sem *root* e qual o custo de desempenho em relação à execução nativa?
- **QP2 — Gerenciamento e redes:** que combinação de HTTP *polling* e WebSockets mantém Host e Nodes conectados com latência aceitável, tolerando as interrupções do Android?
- **QP3 — Recursos e estabilidade:** como os aparelhos se comportam, em disponibilidade, energia e temperatura, ao sustentar cargas contínuas no PRoot?

**Hipótese (H1):** é possível operar, sem *root*, uma frota de smartphones Android que crie ambientes Linux sob demanda e os mantenha disponíveis por longos períodos para cargas leves, desde que (a) a comunicação de controle parta do próprio aparelho (modelo *pull*), (b) os processos sejam supervisionados e reiniciados automaticamente e (c) as otimizações de bateria do Android estejam desativadas para o Termux. A H1 é **confirmada** se forem atendidos os dois critérios principais da Tabela 1: disponibilidade ≥ 99% em 24 h **e** latência de eco do terminal com p95 ≤ 200 ms na rede local sem fio em que os Nodes operam.

## 1.3 Objetivos

O objetivo geral é desenvolver e avaliar uma arquitetura que gerencie ambientes Linux em smartphones Android reaproveitados, sem acesso *root*, como infraestrutura de borda de baixo custo alinhada aos princípios da TI Verde. Os objetivos específicos são:

- **OE1** — Configurar de forma automatizada os Nodes com o Termux e o `proot-distro`, para executar Alpine e Debian sem privilégios administrativos (QP1).
- **OE2** — Desenvolver um agente em Python que colete métricas, descubra os ambientes instalados, execute as tarefas recebidas e sincronize seu estado com o Host (QP2).
- **OE3** — Implementar o Host com Flask e Flask-SocketIO, com um painel web para acompanhar os Nodes e gerenciar o ciclo de vida dos Workers (QP2).
- **OE4** — Oferecer terminal dos Workers no navegador, integrando WebSockets, pseudo-terminais (PTY) e xterm.js (QP2).
- **OE5** — Avaliar experimentalmente a arquitetura: provisionamento, latência do terminal, sobrecarga do PRoot, disponibilidade, energia e temperatura sob cargas leves (QP3 e H1).

## 1.4 Justificativa

O lixo eletrônico cresce cinco vezes mais rápido que a reciclagem documentada (Baldé *et al.*, 2024), e a maior parte da pegada de carbono de um smartphone está na fabricação (Belkhir; Elmeligi, 2018). Prolongar o uso de um aparelho já fabricado é, portanto, uma das formas mais efetivas de reduzir seu impacto: pela métrica de Intensidade de Carbono Computacional (CCI), smartphones reaproveitados têm o melhor potencial entre servidores antigos, *laptops* e telefones (Switzer *et al.*, 2023). Para estudantes, pequenos desenvolvedores e organizações com poucos recursos, aparelhos guardados na gaveta ou doados têm custo de aquisição quase nulo e servem para ensino de sistemas distribuídos, laboratórios de redes e serviços internos. Na Amazônia, o projeto *Rainforest Connection* já usa celulares reciclados como sensores na copa das árvores (Rainforest Connection, 2014), o que mostra que aparelhos descartados podem servir de infraestrutura onde conectividade e orçamento são limitados. A legislação brasileira trata a extensão do ciclo de vida desses produtos como responsabilidade compartilhada (Brasil, 2010; Brasil, 2020).

Do ponto de vista técnico, a literatura sobre *clusters* de smartphones (Marinelli, 2009; Arslan *et al.*, 2012; Büsching; Schildt; Wolf, 2012) trata de computação paralela ou de *frameworks* específicos, e as propostas recentes (Shahrad; Wentzlaff, 2017; Switzer *et al.*, 2023) costumam pressupor sistema substituído ou acesso privilegiado. Há espaço para uma abordagem que preserve o *firmware* original e ofereça a abstração familiar de uma VPS, usando execução em espaço de usuário (PRoot).

## 1.5 Escopo

O trabalho se limita a um protótipo no modelo Host-Node-Worker, que cria ambientes Alpine e Debian usando só o Termux e o PRoot, **sem** *root*, desbloqueio de *bootloader* ou ROM customizada, e que hospeda cargas leves (APIs, *bots*, automações) em **rede local confiável**. Ficam de fora: multilocação com isolamento de segurança entre usuários; cargas pesadas e contínuas; agendamento automático e migração de Workers entre aparelhos; alta disponibilidade do Host; armazenamento distribuído; e exposição de serviços à Internet.

O artigo avalia a versão do DroidServer usada nos experimentos de 16 e 17 de novembro de 2026 (seção 6.1). Funções acrescentadas ao repositório depois disso — o Cloudflare Tunnel, que expõe serviços de um Node à Internet, os Workers de banco de dados PostgreSQL e as abas Arquivos e Monitor do painel — não fazem parte da arquitetura descrita nem da avaliação.

## 1.6 Organização do trabalho

%% tcc %%

A seção 2 traz o referencial teórico, e a 3, os trabalhos relacionados. A seção 4 descreve a metodologia, a 5, o protótipo, e a 6, o protocolo experimental e os resultados. A seção 7 discute os resultados, as limitações e as ameaças à validade, e a seção 8 conclui.

%% /tcc %%

%% topicos %%

A seção 2 traz a fundamentação teórica e os trabalhos relacionados, e a seção 3, a metodologia. A seção 4 apresenta o protótipo, o protocolo experimental e os resultados e discute as questões de pesquisa, a hipótese, as limitações e as ameaças à validade. A seção 5 conclui.

%% /topicos %%
