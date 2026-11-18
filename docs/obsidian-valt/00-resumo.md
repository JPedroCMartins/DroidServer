# Resumo

> [!note] Rascunho
> Preenchido em 16/11/2026 com os resultados medidos (capítulo 9) e completado em 18/11/2026 com a E7 (disponibilidade em 24 h). Limite da NBR 6022: 100 a 250 palavras.

O crescimento do lixo eletrônico — 62 milhões de toneladas em 2022, das quais apenas 22,3% foram formalmente recicladas (BALDÉ et al., 2024) — contrasta com a capacidade ociosa de smartphones descartados por falhas periféricas. Este trabalho apresenta o **DroidServer**, uma arquitetura que transforma smartphones Android sem acesso *root* em nós de um pequeno *cluster*, oferecendo em cada nó servidores virtuais privados no modelo de serviço: ambientes Linux (Alpine e Debian) criados com `proot-distro`, supervisionados pelo Supervisor e operados por um painel web com terminal no navegador. A avaliação, com dois aparelhos (Android 16 e Android 11) em rede Wi-Fi local, mostrou que um ambiente Alpine é instalado em 1,9 s no aparelho e aparece no painel em 16 s (mediana), tempo dominado pelo ciclo de sincronização de 10 s; que o PRoot quase não penaliza processamento e escrita sequencial (+15% e +2%), mas torna operações sobre metadados de arquivos 13 vezes mais lentas e limita uma API HTTP a cerca de 40% da vazão nativa; que a latência de eco do terminal tem p95 de 58 ms em 5 GHz e 360 ms em 2,4 GHz; e que, em 24 h, a API de demonstração manteve 99,94% de disponibilidade, sem nenhum reinício do serviço. Conclui-se que smartphones reaproveitados sustentam serviços leves sem *root*, desde que a comunicação parta do nó, os processos sejam supervisionados e a rede sem fio seja adequada.

**Palavras-chave:** computação de borda; TI verde; Android; PRoot; orquestração de clusters.

---

# Abstract

The growth of electronic waste — 62 million tonnes in 2022, of which only 22.3% was formally recycled (BALDÉ et al., 2024) — contrasts with the idle capacity of smartphones discarded due to peripheral failures. This work presents **DroidServer**, an architecture that turns non-rooted Android smartphones into nodes of a small cluster, offering on each node virtual private servers as a service model: Linux environments (Alpine and Debian) created with `proot-distro`, supervised by Supervisor and operated through a web dashboard with an in-browser terminal. The evaluation, with two devices (Android 16 and Android 11) on a local Wi-Fi network, showed that an Alpine environment is installed in 1.9 s on the device and appears on the dashboard in 16 s (median), a time dominated by the 10 s synchronization cycle; that PRoot barely penalizes computation and sequential writes (+15% and +2%), but makes file-metadata operations 13 times slower and limits an HTTP API to about 40% of native throughput; that terminal echo latency has a p95 of 58 ms on 5 GHz and 360 ms on 2.4 GHz; and that, over 24 h, the demo API kept 99.94% availability, with no service restarts. We conclude that repurposed smartphones can host lightweight services without root, provided that communication is initiated by the node, processes are supervised and the wireless network is adequate.

**Keywords:** edge computing; green IT; Android; PRoot; cluster orchestration.
