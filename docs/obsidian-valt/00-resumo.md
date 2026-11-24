# Resumo

> [!note] Rascunho
> Revisto em 24/11/2026 com o parecer do orientador: aparelho de cada experimento, confirmação parcial da H1 e "gerenciamento" no lugar de "orquestração". Limite da NBR 6022 e das revistas: 100 a 250 palavras. A revista escolhida é a Tópicos (título e resumo em português e inglês). Os títulos ficam no gerador (`META` em `docs/gerador-docx/gerar.mjs`) e no README do vault.

O crescimento do lixo eletrônico — 62 milhões de toneladas em 2022, das quais só 22,3% foram formalmente recicladas (BALDÉ et al., 2024) — contrasta com a capacidade ociosa de smartphones descartados por falhas periféricas. Este trabalho apresenta o **DroidServer**, uma arquitetura que gerencia uma pequena frota de smartphones Android sem acesso *root* e oferece, em cada aparelho, ambientes Linux no modelo de serviço de um servidor virtual privado: Alpine e Debian criados com o proot-distro, mantidos pelo Supervisor e operados por um painel web com terminal no navegador. A avaliação usou dois aparelhos em Wi-Fi doméstico: um com Android 16, para provisionamento, sobrecarga, terminal e vazão, e um com Android 11, para disponibilidade e consumo. Um ambiente Alpine é instalado em 1,9 s e aparece no painel em 16 s (mediana), tempo dominado pelo ciclo de sincronização de 10 s. O PRoot quase não penaliza processamento e escrita sequencial, mas torna operações sobre metadados de arquivos 13 vezes mais lentas e limita uma API HTTP a cerca de 40% da vazão nativa. O p95 da latência de eco do terminal foi de 58 ms em 5 GHz e de 360 ms em 2,4 GHz, acima do critério de 200 ms. Em 24 h, o serviço de demonstração respondeu a 99,94% das verificações locais, sem reinícios. A hipótese foi confirmada parcialmente: a disponibilidade foi atingida, e a latência, só em 5 GHz.

**Palavras-chave:** computação de borda; TI verde; Android; PRoot; gerenciamento de frota de dispositivos.

---

# Abstract

The growth of electronic waste — 62 million tonnes in 2022, of which only 22.3% was formally recycled (BALDÉ et al., 2024) — contrasts with the idle capacity of smartphones discarded due to peripheral failures. This work presents **DroidServer**, an architecture that manages a small fleet of non-rooted Android smartphones and offers, on each device, Linux environments following the service model of a virtual private server: Alpine and Debian created with proot-distro, kept running by Supervisor and operated through a web dashboard with an in-browser terminal. The evaluation used two devices on a home Wi-Fi network: one running Android 16, for provisioning, overhead, terminal and throughput, and one running Android 11, for availability and resource usage. An Alpine environment is installed in 1.9 s and appears on the dashboard in 16 s (median), a time dominated by the 10 s synchronization cycle. PRoot barely penalizes computation and sequential writes, but makes file-metadata operations 13 times slower and limits an HTTP API to about 40% of native throughput. The p95 terminal echo latency was 58 ms on 5 GHz and 360 ms on 2.4 GHz, above the 200 ms criterion. Over 24 h, the demo service answered 99.94% of local checks, with no restarts. The hypothesis was partially confirmed: the availability criterion was met, and the latency criterion only on 5 GHz.

**Keywords:** edge computing; green IT; Android; PRoot; device fleet management.

