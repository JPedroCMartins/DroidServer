# 2. Problema de Pesquisa

A proposição de reaproveitar hardware móvel obsoleto como infraestrutura computacional expõe um paradoxo tecnológico contemporâneo: centenas de milhões de smartphones são descartados anualmente (SWITZER et al., 2023), apesar de possuírem processadores *multicore* ARM e quantidades de memória RAM frequentemente iguais ou superiores às instâncias básicas de VPS comercializadas por provedores de nuvem. No entanto, a conversão direta desses dispositivos em nós de um *cluster* esbarra em barreiras arquiteturais impostas pelo próprio sistema operacional.

O Android, embora construído sobre o *kernel* Linux, é projetado para o consumo individual e para a eficiência energética. Para garantir segurança e autonomia de bateria, cada aplicativo executa em uma *sandbox* com identificador de usuário próprio e políticas obrigatórias do SELinux (ANDROID OPEN SOURCE PROJECT, 2024a). Sem privilégios administrativos (*root*), torna-se inviável usar motores de conteinerização padrão da indústria, como o Docker, que dependem de *namespaces* e *cgroups* do *kernel* (MERKEL, 2014; RICE, 2020).

Além das limitações de privilégio, o Android impõe desafios agressivos à persistência de execução. Desde o Android 6.0, os modos *Doze* e *App Standby* adiam o acesso à rede e à CPU de aplicativos em segundo plano (ANDROID DEVELOPERS, 2024); o *daemon* `lmkd` (*Low Memory Killer*) encerra processos para liberar memória (ANDROID OPEN SOURCE PROJECT, 2024b); e, a partir do Android 12, o chamado *phantom process killer* encerra processos-filho de aplicativos quando o total ultrapassa 32 ou quando consomem CPU excessiva — comportamento relatado pela comunidade do Termux como encerramentos com `signal 9` (TERMUX, 2021). Para um servidor, que precisa manter portas de rede abertas continuamente, esse comportamento resulta em quedas de conexão e perda de estado das aplicações hospedadas.

O desafio de engenharia, portanto, não é apenas físico, mas predominantemente de software e de arquitetura de redes: é necessário estabelecer comunicação estável e uma camada de isolamento viável sem alterar o *firmware* original dos aparelhos, mantendo a premissa de baixo custo e facilidade de implantação proposta pela TI Verde.

Diante desse cenário, a pesquisa é norteada pela seguinte questão central:

> **Como projetar e orquestrar um *cluster* de computação distribuída utilizando smartphones Android reaproveitados, contornando as restrições de privilégio e de gerenciamento de processos do sistema nativo, para provisionar e gerenciar ambientes Linux isolados de forma estável?**

O problema desdobra-se nos seguintes questionamentos secundários:

- **QP1 — Isolamento:** Como provisionar distribuições Linux (Alpine, Debian, Arch) dentro do Android sem *root*, garantindo às aplicações hospedadas acesso satisfatório ao sistema de arquivos e à rede, e qual é o custo de desempenho dessa abordagem em relação à execução nativa?
- **QP2 — Orquestração e redes:** Qual combinação de modelos de comunicação (HTTP *polling* e WebSockets) mantém a conectividade entre o Host e os Nodes com latência aceitável, tolerando as interrupções impostas pelo Android?
- **QP3 — Recursos e estabilidade:** Como os aparelhos se comportam, em termos de disponibilidade, consumo de energia e temperatura, ao sustentar cargas contínuas dentro de ambientes PRoot?

## 2.1 Hipótese

**H1:** É possível operar, sem acesso *root*, um *cluster* de smartphones Android que provisione ambientes Linux sob demanda e os mantenha disponíveis por longos períodos para cargas leves, desde que (a) a comunicação de controle seja iniciada pelo próprio nó (modelo *pull*), (b) os processos sejam supervisionados e reiniciados automaticamente e (c) as otimizações de bateria do Android sejam desativadas para o Termux.

A hipótese é considerada **confirmada** se os critérios definidos na nota [09 — Avaliação experimental](09-avaliacao-experimental.md) forem atendidos (por exemplo, disponibilidade ≥ 99% em 24 h e latência de terminal p95 ≤ 200 ms em LAN — valores a confirmar com o orientador).
