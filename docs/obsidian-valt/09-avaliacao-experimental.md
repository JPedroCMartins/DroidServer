# 9. Protocolo de Avaliação Experimental

> [!info] Executado em 16/11/2026 (E7 pendente)
> Este capítulo define **o que medir, como e com quais critérios**, para que os resultados sejam reprodutíveis (JAIN, 1991), e registra os resultados (seção 9.5). Os *scripts* e os dados brutos (CSV) estão em `bench/` no repositório; as figuras são geradas por `bench/graficos.py`.

## 9.1 Ambiente de testes

| Item | Descrição |
|---|---|
| Host | PC Intel Xeon E5-2620 v3 (12 *threads*), 39 GB de RAM, Debian 13 (*trixie*), kernel 6.12, Python 3.13; **cabeado** ao roteador |
| Rede | Roteador doméstico; os Nodes no Wi-Fi **2,4 GHz** (E4 também em 5 GHz, para comparação). Na 2,4 GHz, um `ping` do Host ao Node 1 mostrou média de 43 ms e pacotes duplicados (indício de repetidor/*mesh*) |
| Node 1 | Xiaomi **POCO X6 Pro 5G** (2311DRK48G), MediaTek Dimensity 8300 (MT6897, 8 núcleos), 7,3 GB de RAM, **Android 16** (HyperOS 3), kernel 6.1; E1–E5 e E8 |
| Node 2 | **Motorola moto e40**, Unisoc T700 (ums512, 8 núcleos), 3,4 GB de RAM, **Android 11**; E7 (24 h) e E10 |
| Termux / proot-distro | Termux 0.118.1 (Node 1) e 0.118.3 (Node 2); proot-distro 5.10.3; proot 5.1.107; Supervisor 4.3.0; Python 3.14 (Termux) |
| Workers | Alpine 3.24 (Python 3.14 via `apk`) e Debian 13 (Python 3.13) |
| Configuração Android | Agente com `termux-wake-lock` (`run.sh -d`); bateria do Termux sem restrições; aparelhos na tomada |

Recomenda-se ao menos três aparelhos de gerações diferentes para observar a heterogeneidade; foram usados dois (um intermediário-*premium* de 2024 com Android 16 e um de entrada de 2021 com Android 11).

## 9.2 Experimentos

| ID | Questão | Métrica | Procedimento | Repetições |
|---|---|---|---|---|
| E1 | QP1 | **Tempo de provisionamento** por distribuição (s) | Criar Workers Alpine e Debian pelo painel; medir do clique até `RUNNING` (instrumentar `ts` da tarefa e do resultado) | 10 por distro × Node |
| E2 | QP1 | **Uso de disco** por Worker (MB) | `du -sh` do *rootfs* após a criação | 1 por distro |
| E3 | QP1 | **Sobrecarga do PRoot** (%) | Rodar o mesmo *benchmark* no Termux nativo e dentro do Worker: CPU (`sysbench cpu`), E/S de arquivos (`sysbench fileio` ou `fio`), chamadas de sistema (compilar um projeto pequeno; `apk add`/`apt install` de um pacote) | 10 cada |
| E4 | QP2 | **Latência de eco do terminal** (ms) | Enviar um caractere e medir o tempo até o eco voltar ao navegador (instrumentar o JS com `performance.now()`) | 1000 amostras; reportar mediana, p95, p99 |
| E5 | QP2 | **Latência de entrega de tarefa** (s) | Tempo entre o enfileiramento no Host e o início da execução no Node; esperado ≈ U(0, 10 s) | 50 |
| E6 | QP2 | **Tempo de detecção de falha** (s) e falsos positivos | Desligar o Wi-Fi do Node e medir até o painel mostrar *Offline*; contar transições *Offline* indevidas em 24 h | 20 / 24 h |
| E7 | QP3 | **Disponibilidade** (%) | Worker com um servidor HTTP simples; o próprio agente faz `GET` local no serviço a cada 10 s e grava no registro do celular (seção 8.5.1), por 24 h, com o painel ligado ou não; disponibilidade = amostras OK / amostras esperadas (lacunas no registro contam como indisponibilidade). Registrar cada reinício (PID novo) | 1 rodada por configuração |
| E8 | QP3 | **Vazão de um microsserviço** (req/s) e CPU do Worker (`cpu_workers`) | `wrk` ou `hey` contra uma API leve (Flask/FastAPI ou Go) no Worker; comparar com o mesmo serviço em uma VPS básica ou num Raspberry Pi, se disponível | 5 |
| E9 | QP3 | **Temperatura e energia** | Ler `/sys/class/thermal/*/temp` e `/sys/class/power_supply/battery/*` (quando acessíveis) ou usar um medidor USB na tomada, em repouso e sob carga E8 | Contínuo durante E7/E8 |
| E10 | QP3 | **Consumo do agente** | CPU (métrica `cpu_termux` com os Workers parados) e RSS do `node.py` e do `supervisord` em repouso | 1 h |

### Fatores e configurações para E7

Compare pelo menos duas configurações para sustentar a hipótese H1:

1. Android padrão (otimização de bateria ativa, sem *wake-lock*);
2. Otimização de bateria desativada para o Termux + `termux-wake-lock` + *phantom process killer* desativado (Android 12+).

## 9.3 Critérios de aceitação (proposta — validar com o orientador)

| Critério | Limite | Resultado (16/11/2026) |
|---|---|---|
| Disponibilidade do Worker em 24 h (configuração 2) | ≥ 99% | ⏳ E7 pendente (parciais: 99,94% em 4,4 h) |
| Latência de eco do terminal, p95, em LAN | ≤ 200 ms | ✅ 58 ms em 5 GHz · ❌ 360 ms em 2,4 GHz |
| Detecção de Node *offline* | ≤ 35 s | ✅ por construção: `STALE_TIMEOUT` = 25 s + até 10 s até o próximo *refresh* (não medido; E6 fora do escopo) |
| Provisionamento de Worker Alpine | ≤ 2 min | ✅ 1,9 s no aparelho; 16 s (mediana) a 32 s (máx.) no painel |

## 9.4 Análise

Reportar média, desvio-padrão e intervalo de confiança de 95% (ou mediana e percentis para latências, que costumam ter distribuição assimétrica). Gráficos sugeridos: *boxplot* do tempo de provisionamento por distribuição; CDF da latência do terminal; linha do tempo de disponibilidade com os eventos de reinício; barras de sobrecarga do PRoot por tipo de carga.

## 9.5 Resultados

Estatísticas: média ± IC 95% (*t* de Student) para tempos com poucas repetições; mediana e percentis para latências e vazão (distribuições assimétricas). Dados brutos em `bench/resultados/`.

### E1, E2 e E5 — Provisionamento (Node 1, 2,4 GHz, 5 repetições por condição)

| Distribuição | Cache | Instalação no aparelho (mediana; mín–máx) | Percebido no painel (mediana; mín–máx) | Disco (E2) |
|---|---|---|---|---|
| Alpine | com | **1,9 s** (1,9–2,0) | 16,2 s (11,6–19,2) | 9 MB |
| Alpine | sem | 8,7 s (7,3–14,1) | 18,2 s (12,1–31,8) | 9 MB |
| Debian | com | 4,2 s (4,2–5,7) | 19,2 s (12,6–20,2) | 153 MB |
| Debian | sem | 17,0 s (16,8–22,9) | 24,8 s (21,8–39,4) | 153 MB |

![[figuras/e1_provisionamento.png]]

*Figura 9.1 — Tempo de provisionamento: no aparelho e percebido no painel (traço = mediana).*

Todas as 20 criações e remoções foram bem-sucedidas. O tempo percebido é **dominado pelo modelo de *polling*** e não pela instalação: a **E5** (do clique até o agente receber a tarefa) teve média de 4,5 ± 1,5 s e mediana de 4,6 s (n = 20; 0–10 s), compatível com a espera uniforme de até um ciclo de 10 s, e o retorno ao painel soma outro ciclo. Pelo mesmo motivo, a remoção levou ~20 s (dois ciclos) em todas as repetições. Mesmo no pior caso (Debian sem cache, 39 s), o critério de ≤ 2 min para o Alpine é atendido com folga.

Nota de método: um piloto em 5 GHz mediu entregas sempre próximas de 10 s, porque cada criação era disparada logo após um *sync*; a versão final insere um atraso aleatório de 0–10 s antes de cada criação. O alinhamento dos relógios do PC e do celular por SSH tem incerteza de ~0,5 s (duas entregas negativas de até −0,54 s).

### E3 — Sobrecarga do PRoot (Node 1, Worker Debian, 10 repetições, ordem alternada)

| Carga | Termux nativo (mediana) | Worker/PRoot (mediana) | Razão |
|---|---|---|---|
| CPU pura (sha256 de 256 MB) | 0,43 s | 0,50 s | 1,2× (+15%) |
| *fork* + *exec* (300 × `ls`) | 5,53 s | 15,05 s | 2,7× |
| 1000 arquivos pequenos (criar + apagar) | 0,13 s | 1,70 s | **13,4×** |
| Escrita sequencial (200 MB + `fsync`) | 0,45 s | 0,46 s | 1,0× |
| Inicialização do Python (20 ×) | 0,90 s | 2,09 s | 2,3× |

![[figuras/e3_sobrecarga_proot.png]]

*Figura 9.2 — Sobrecarga do PRoot por tipo de carga.*

O padrão confirma o mecanismo do PRoot (seção 5): cada chamada de sistema que envolve caminhos (`open`, `stat`, `unlink`, `execve`) é interceptada via `ptrace` e traduzida, enquanto computação pura e E/S em blocos grandes quase não pagam custo. Serviços que fazem muitas operações de metadados de arquivo (compilação, instalação de pacotes, bancos com muitos arquivos) sofrem mais; serviços de rede e CPU, menos.

### E4 — Latência de eco do terminal (Node 1, 1000 medições por condição)

| Condição | Mediana | p95 | p99 | > 200 ms | Sem eco em 3 s |
|---|---|---|---|---|---|
| 5 GHz, agente em *long-polling* (antes da correção) | 56 ms | 321 ms | 601 ms | 9,4% | 19 |
| 5 GHz, agente em WebSocket | **17 ms** | **58 ms** | 186 ms | 0,9% | 0 |
| 2,4 GHz, agente em WebSocket | 45 ms | 360 ms | 560 ms | 9,4% | 0 |

![[figuras/e4_latencia_terminal_cdf.png]]

*Figura 9.3 — Distribuição acumulada da latência de eco.*

A medição revelou um defeito: o agente iniciava o Socket.IO por *long-polling* e nem sempre migrava para WebSocket, gerando ~10 requisições/s ao Host com o terminal em uso, *syncs* com *timeout* e ecos perdidos. Com a conexão direta por WebSocket, o critério (p95 ≤ 200 ms) é atendido em 5 GHz. **Em 2,4 GHz não é atendido** (p95 de 360 ms): o terminal continua utilizável na mediana, mas ~1 em cada 10 teclas passa de 200 ms, efeito do meio sem fio (latência de 43 ms e duplicatas no `ping`), não do sistema.

### E8 — Vazão da API de demonstração (Node 1, 2,4 GHz, 5 repetições de 20 s)

A mesma `app.py` (servidor HTTP da biblioteca padrão do Python, *threaded*) no Worker Alpine e no Termux nativo; carga com `hey` a partir do Host. Vazão útil = respostas 2xx por segundo.

| Conexões simultâneas | Worker (mediana) | Nativo (mediana) | Worker/nativo | p95 no Worker |
|---|---|---|---|---|
| 1 | 24 req/s | 36 req/s | 0,67 | 76 ms |
| 10 | 62 req/s | 137 req/s | 0,45 | 329 ms |
| 50 | 60 req/s | 148 req/s | 0,40 | 1,25 s |

![[figuras/e8_vazao.png]]

*Figura 9.4 — Vazão por número de conexões simultâneas.*

Com uma conexão, a vazão é limitada pela ida e volta na rede; com concorrência, a sobrecarga do PRoot nas chamadas de rede e de *threads* aparece: o Worker satura em ~60 req/s, cerca de **40–45% da vazão nativa**. Com 50 conexões houve *timeouts* nos dois alvos (124 no Worker e 56 no nativo, em ~7–15 mil requisições). Para uma API leve de uso pessoal ou de laboratório, ~60 req/s é suficiente; para cargas maiores, o serviço deveria rodar fora do PRoot ou em vários Nodes.

Nota de método: as versões do Python diferem (3.14 no Termux e no Alpine; o app é o mesmo). Durante a E8, o Node 2 instalava pacotes no mesmo Wi-Fi (descompactação local, sem *download* relevante).

### E10 — Consumo do próprio DroidServer

| Node | RSS do agente | RSS do `supervisord` | CPU do DroidServer em repouso (% do aparelho) |
|---|---|---|---|
| POCO X6 Pro (Android 16) | ~25 MB | ~10 MB | ~0,6% |
| moto e40 (Android 11) | ~43 MB | ~23 MB | ~0,1–0,7% |

*(Valores iniciais; o resumo completo sai com a E7.)*

### E7 e E6 — Disponibilidade em 24 h (Node 2, pendente)

A rodada completa de 24 h no moto e40 ainda não foi concluída. Duas rodadas parciais (Worker Alpine com a API de demonstração, porta 8080; aparelho na tomada e tela apagada; uma amostra a cada 10 s):

| Rodada | Duração | Disponibilidade | Falhas | Reinícios do serviço | Quedas do Node (E6) | Interrupção |
|---|---|---|---|---|---|---|
| 1 | 4,42 h (1593 amostras) | 99,94% | 1 *timeout* de 10 s | 0 | 0 | queda de energia no PC (o celular seguiu na bateria; o serviço ficou 6 h no ar sem reiniciar) |
| 2 | 0,23 h (82 amostras) | 100% | 0 | 0 | 0 | adiada pelo usuário |

As rodadas 1 e 2 mediam a partir do PC, pelo painel; a rodada 1 terminou justamente porque o PC desligou. A rodada definitiva usa o registro local do Node (seção 8.5.1), que não depende do PC: o `GET` parte do próprio celular, pela interface local. Assim, a E7 mede se o serviço permanece vivo e respondendo no Android, que é o que a H1 afirma, e não a estabilidade do Wi-Fi entre o celular e o PC (a latência pela rede já é tratada na E4). Uma amostra ausente (agente parado, aparelho desligado ou Termux congelado pelo sistema) conta como indisponibilidade, o que torna a medida conservadora.

*(Preencher com a rodada de 24 h: `uv run bench/e7_disponibilidade.py --worker demo_api --inicio "<data hora>" --horas 24`.)*

### E9 — Temperatura e energia

Não executado: no Android 16, `/sys/class/thermal/*` e `/sys/class/power_supply/battery/*` retornam *Permission denied* sem *root*; registra-se como limitação (seção 10).
