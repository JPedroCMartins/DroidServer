# 3. Trabalhos Relacionados

## 3.1 Computação distribuída em smartphones

O **Hyrax** (MARINELLI, 2009) portou o Hadoop para Android e rodou MapReduce em um *cluster* de telefones, com desempenho limitado pelo hardware da época. O **Computing While Charging** (ARSLAN et al., 2012) usou os celulares de uma empresa enquanto carregavam à noite, com um escalonador atento à bateria. O **DroidCluster** (BÜSCHING; SCHILDT; WOLF, 2012) instalou Debian no cartão SD e mediu o *cluster* com o LINPACK.

## 3.2 Reúso de aparelhos descomissionados

Shahrad e Wentzlaff (2017) propuseram servidores densos feitos de smartphones usados e mostraram que a energia de fabricação domina o consumo ao longo da vida útil. O **Junkyard Computing** (SWITZER et al., 2023) rodou microsserviços completos em dez Pixel 3A com o Android trocado pelo Ubuntu Touch e Docker Swarm, propôs a métrica CCI e concluiu que celulares reaproveitados superam servidores e *laptops* antigos em carbono por computação.

## 3.3 Clusters de baixo custo com computadores de placa única

*Clusters* de Raspberry Pi servem de modelos em escala de *data centers* para ensino e pesquisa (ABRAHAMSSON et al., 2013; TSO et al., 2013; JOHNSTON et al., 2018), mas exigem comprar hardware novo, o que o DroidServer quer evitar.

## 3.4 Execução de ambientes Linux sem privilégios

O **udocker** (GOMES et al., 2018) roda imagens Docker sem *root* em HPC usando o PRoot. O UserLAnd (CYPHERPUNK ARMORY, [20--]), o Andronix (ANDRONIX, [20--]) e o próprio `proot-distro` (TERMUX, [20--]) oferecem Linux no Android sem *root*, mas para um único usuário interativo no próprio aparelho, sem gerenciamento remoto de vários aparelhos.

## 3.5 Quadro comparativo

| Trabalho | Exige *root*/troca de SO | Abstração oferecida | Gerência de vários nós | Interface web | Foco |
|---|---|---|---|---|---|
| Hyrax (2009) | Não (app Android) | Tarefa MapReduce | Sim (Hadoop) | Não | Processamento em lote |
| CWC (2012) | Não (app) | Tarefa | Sim (escalonador) | Não | Computação durante a carga |
| DroidCluster (2012) | Sim (Debian no SD) | Processo MPI | Sim (MPI) | Não | HPC / *benchmark* |
| Shahrad e Wentzlaff (2017) | Não especificado | Servidor | Proposta, sem implementação | Não | TCO / energia |
| Junkyard (2023) | Sim (Ubuntu Touch com *kernel* modificado) | Microsserviço (Docker) | Sim (Docker Swarm) | Não | Carbono |
| udocker (2018) | Não | Contêiner | Não | Não | HPC sem *root* |
| **DroidServer** | **Não** | **Ambiente Linux tipo VPS** | **Sim (Host–Node, sem escalonador)** | **Sim, com terminal** | **Reúso sem *root*** |

*Quadro 2 — Trabalhos relacionados.*

**Lacuna:** nenhum trabalho encontrado combina (i) aparelhos com *firmware* original e sem *root*, (ii) a abstração de um servidor Linux de uso geral e (iii) um plano de gerenciamento com painel e terminal remoto. Essa é a contribuição do DroidServer.
