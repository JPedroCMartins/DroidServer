# 11. Conclusão

Este trabalho propôs e avaliou o **DroidServer**, uma arquitetura que transforma smartphones Android reaproveitados, sem *root*, em nós de um pequeno *cluster* que oferece servidores virtuais privados no modelo de serviço. O protótipo cumpriu os objetivos de implementação: um único *script* prepara o aparelho (OE1); o agente coleta métricas, executa tarefas e sincroniza o estado (OE2); o painel web gerencia Nodes, Workers e serviços (OE3); e o terminal funciona no navegador (OE4). A avaliação (OE5) foi feita em dois aparelhos de gerações diferentes.

## 11.1 Respostas às questões de pesquisa

**QP1 — Isolamento.** É possível rodar distribuições Linux completas no Android sem *root*: um Worker Alpine instala em 1,9 s e ocupa 9 MB. O custo depende da carga: cálculo e escrita sequencial quase não perdem desempenho, mas operações de arquivo ficam até 13× mais lentas, e uma API HTTP entrega cerca de 40% da vazão nativa. O isolamento é só do sistema de arquivos.

**QP2 — Orquestração e redes.** *Polling* iniciado pelo Node para o controle e WebSocket para o tempo real funcionaram bem. O *polling* de 10 s domina o tempo percebido (um Worker aparece no painel em 16 s), e o terminal precisa de WebSocket direto para ter p95 de 58 ms em 5 GHz. Em 2,4 GHz, o p95 de 360 ms ficou acima do critério por causa da rede sem fio. Identificar os Nodes por *token* absorveu as trocas de IP por DHCP.

**QP3 — Recursos e estabilidade.** O DroidServer consome pouco: cerca de 20 MB de RAM no agente e menos de 2% da CPU do aparelho. No moto e40, a API ficou 99,94% disponível em 24 h, sem nenhum reinício. Temperatura e energia não puderam ser medidas sem *root*.

## 11.2 Hipótese

As condições (a) comunicação iniciada pelo nó e (b) supervisão dos processos foram implementadas e se mostraram suficientes: o modelo *pull* absorveu trocas de IP e reinícios do Host, e o Supervisor manteve os serviços no ar. Com 99,94% em 24 h, o critério de ≥ 99% foi atendido, e a **H1 é considerada confirmada** com a condição (c), otimizações de bateria desativadas. Como a comparação com o Android em configuração padrão não foi feita, não se pode afirmar que (c) é necessária, apenas que é suficiente nos aparelhos testados.

## 11.3 Contribuições e considerações finais

As contribuições são: um protótipo funcional e de código aberto que orquestra smartphones sem *root*, com painel, terminal no navegador e segurança mínima; medições reprodutíveis, com *scripts* e dados no repositório, do custo do PRoot, da latência do terminal e do provisionamento; e a identificação de problemas que só aparecem em aparelhos reais, como a medição de CPU sem *root* e o efeito do `ptrace` sobre operações de arquivo.

Smartphones reaproveitados são uma infraestrutura viável para serviços leves em rede local, como APIs, *bots*, automações e ambientes de estudo, com custo de *hardware* quase nulo e sem alterar o *firmware*. Os limites estão quantificados: o PRoot não é virtualização, operações de arquivo ficam uma ordem de grandeza mais lentas e a qualidade do Wi-Fi pesa tanto quanto o próprio sistema. TLS, escalonamento automático e medição de energia são os próximos passos para levar o protótipo ao uso contínuo.
