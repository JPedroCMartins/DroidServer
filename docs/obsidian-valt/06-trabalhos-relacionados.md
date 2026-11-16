# 6. Trabalhos Relacionados

Esta seção posiciona o DroidServer em relação a trabalhos que usam smartphones como recurso computacional ou que executam ambientes Linux sem privilégios.

## 6.1 Computação distribuída em smartphones

- **Hyrax** (MARINELLI, 2009) portou o Hadoop para Android e executou tarefas MapReduce em um *cluster* de telefones, concluindo que era viável, mas com desempenho e eficiência limitados pelo hardware da época.
- **Computing While Charging (CWC)** (ARSLAN et al., 2012) propôs usar smartphones de uma empresa enquanto carregam à noite como infraestrutura de computação distribuída, com um escalonador que considera a heterogeneidade dos aparelhos e o impacto na bateria.
- **DroidCluster** (BÜSCHING; SCHILDT; WOLF, 2012) avaliou um *cluster* de smartphones executando uma distribuição Debian instalada no cartão SD e mediu o desempenho com o *benchmark* LINPACK, argumentando que "as ruas estão pavimentadas" de *clusters* em potencial.

## 6.2 Reúso de aparelhos descomissionados

- **Shahrad e Wentzlaff (2017)** propuseram construir servidores densos com smartphones usados e parcialmente quebrados, analisando o custo total de propriedade e mostrando que a energia de fabricação domina o consumo ao longo da vida útil do aparelho.
- **Junkyard Computing** (SWITZER et al., 2023) analisou a execução de aplicações de microsserviços completas (o *DeathStarBench*) em *clusters* de smartphones descartados, propôs a métrica CCI (gramas de CO₂ por unidade de computação) e concluiu que smartphones reaproveitados superam servidores e *laptops* antigos em carbono por computação. O trabalho recebeu o prêmio de *Distinguished Paper* do ASPLOS 2023.

## 6.3 Clusters de baixo custo com computadores de placa única

*Clusters* de Raspberry Pi foram usados como modelos em escala de *data centers* para ensino e pesquisa (ABRAHAMSSON et al., 2013; TSO et al., 2013; JOHNSTON et al., 2018). Eles demonstram o valor pedagógico de *clusters* baratos, mas exigem compra de hardware novo — exatamente o que o DroidServer procura evitar.

## 6.4 Execução de ambientes Linux sem privilégios

O **udocker** (GOMES et al., 2018) executa imagens Docker sem *root* em ambientes multiusuário de HPC, usando o PRoot como motor padrão. Aplicativos como UserLAnd e Andronix, e o próprio `proot-distro` do Termux, oferecem distribuições Linux em Android sem *root*, mas voltadas a um único usuário interativo, sem orquestração entre aparelhos.

## 6.5 Quadro comparativo

| Trabalho | Exige *root*/troca de SO | Abstração oferecida | Orquestração multi-nó | Interface web | Foco |
|---|---|---|---|---|---|
| Hyrax (2009) | Não (app Android) | Tarefa MapReduce | Sim (Hadoop) | Não | Processamento em lote |
| CWC (2012) | Não (app) | Tarefa | Sim (escalonador) | Não | Computação durante a carga |
| DroidCluster (2012) | Sim (Debian no SD) | Processo MPI | Sim (MPI) | Não | HPC / *benchmark* |
| Shahrad & Wentzlaff (2017) | Não especificado | Servidor | Proposta | Não | TCO / energia |
| Junkyard (2023) | Sim (aparelhos preparados) | Microsserviço | Sim | Não | Carbono |
| udocker (2018) | Não | Contêiner | Não | Não | HPC sem *root* |
| **DroidServer** | **Não** | **Ambiente Linux tipo VPS** | **Sim (Host–Node)** | **Sim, com terminal** | **Reúso sem *root*** |

*Quadro 2 — Trabalhos relacionados. Fonte: elaborado pelo autor. Verifique os detalhes de cada linha na leitura completa dos artigos antes de publicar.*

**Lacuna:** nenhum dos trabalhos encontrados combina (i) aparelhos com *firmware* original e sem *root*, (ii) a abstração de um servidor Linux de uso geral e (iii) um plano de controle com painel e terminal remoto. Esta é a contribuição pretendida pelo DroidServer.
