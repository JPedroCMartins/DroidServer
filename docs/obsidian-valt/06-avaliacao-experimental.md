# 6. Avaliação Experimental

> [!info] Executado de 16 a 17/11/2026
> Os *scripts* e os dados brutos (CSV) estão em `bench/` no repositório; as figuras são geradas por `bench/graficos.py`. A versão longa deste capítulo, com uma tabela por experimento, está no *commit* 17f9f75.

## 6.1 Ambiente e versão avaliada

O Host foi um PC Debian 13 (Xeon E5-2620 v3, 39 GB de RAM), ligado ao roteador doméstico por cabo. Foram usados dois Nodes, ambos na tomada, com a otimização de bateria desativada para o Termux e `termux-wake-lock` ativo: o **Node 1**, um Xiaomi POCO X6 Pro (Dimensity 8300, 7,3 GB, Android 16), e o **Node 2**, um Motorola moto e40 (Unisoc T700, 3,4 GB, Android 11). Os Nodes ficaram no Wi-Fi de 2,4 GHz; só a E4 foi repetida em 5 GHz, para comparação. Na rede de 2,4 GHz, um `ping` do Host ao Node 1 teve média de 43 ms e pacotes duplicados. Os Workers usaram Alpine 3.24 e Debian 13, com proot-distro 5.10.3 e Supervisor 4.3.0.

Os experimentos E1 a E5 e E8 rodaram com o código do *commit* `a579186` (16/11/2026), e a E7 e a E10, com o do *commit* `3cd3e58` (16/11/2026), que acrescentou o registro local de métricas no Node. Código, *scripts*, dados brutos e notas de método estão em https://github.com/JPedroCMartins/DroidServer.

## 6.2 Protocolo

O Quadro 3 resume o que foi medido, em qual aparelho e rede, com quantas repetições e com qual ferramenta. Cada experimento rodou sozinho, para que uma carga não distorcesse a outra.

| ID | Métrica | Aparelho e rede | Procedimento e repetições |
|---|---|---|---|
| E1, E2, E5 | Tempo de provisionamento, disco por Worker e atraso de entrega da tarefa | Node 1, 2,4 GHz | Criação e remoção pela API do painel; Alpine e Debian, com e sem o pacote da distribuição em *cache* (o "sem *cache*" roda `proot-distro clear-cache` antes); **5 repetições por combinação** (20 criações); atraso aleatório de **0 a 10 s** antes de cada criação, para a fase em relação ao *sync* ser uniforme; instalação lida do log do agente e disco com `du`, por SSH; relógios do PC e do celular alinhados por SSH a cada repetição |
| E3 | Sobrecarga do PRoot | Node 1 (cargas locais, via SSH) | Cinco cargas com os mesmos comandos no Termux nativo e num Worker Debian: CPU (sha256 de 256 MB), 300 × `ls` (*fork* + *exec*), criar e apagar 1000 arquivos, escrita sequencial de 200 MB com `fsync` e 20 inicializações do Python; **10 repetições**, alternando a ordem nativo/PRoot |
| E4 | Latência de eco do terminal | Node 1, 5 GHz e 2,4 GHz | Tecla e *backspace* enviadas pelo WebSocket do painel até o eco voltar; **1000 medições por condição** |
| E7 | Disponibilidade em 24 h | Node 2, 2,4 GHz, tela apagada | O agente faz `GET` local no serviço de um Worker Alpine **a cada 10 s** e grava no celular; **1 rodada de 24 h**; amostra ausente conta como falha |
| E8 | Vazão de uma API HTTP | Node 1, 2,4 GHz | `hey` no Host contra a mesma `app.py` no Worker Alpine e no Termux nativo, com **1, 10 e 50 conexões**, **5 repetições de 20 s** cada |
| E10 | Consumo do DroidServer | Node 2, durante a E7 | RSS do agente e do `supervisord` e CPU dos processos do Termux, do registro local da E7 |

*Quadro 3 — Protocolo dos experimentos.*

Para tempos com poucas repetições (E1), relatam-se a mediana e o intervalo entre mínimo e máximo; para o atraso de entrega (E5, n = 20), a média com intervalo de confiança de 95% (*t* de Student); para latências e vazão, de distribuição assimétrica, a mediana e os percentis (JAIN, 1991). Os critérios de aceitação estão na Tabela 1. Dois experimentos previstos não foram feitos. A medição de temperatura e energia (E9) não foi possível: nos dois aparelhos, a leitura de `/sys/class/thermal` e `/sys/class/power_supply` é negada sem *root*. O tempo de detecção de falha (E6) não foi medido à parte.

## 6.3 Resultados

| Critério | Limite | Resultado | Situação |
|---|---|---|---|
| Disponibilidade do serviço em 24 h (Node 2) | ≥ 99% | 99,94%, sem reinícios do serviço | Atendido |
| Latência de eco do terminal, p95, em LAN (Node 1) | ≤ 200 ms | 58 ms em 5 GHz; 360 ms em 2,4 GHz | Atendido só em 5 GHz |
| Detecção de Node *offline* | ≤ 35 s | 25 s sem *sync* + até 10 s de atualização do painel | Não medido (atendido por projeto) |
| Provisionamento de Worker Alpine (Node 1) | ≤ 2 min | 1,9 s no aparelho; 16 s (mediana) no painel | Atendido |

*Tabela 1 — Critérios de aceitação e resultados.*

**Provisionamento (E1, E2, E5).** As 20 criações e remoções deram certo. Com o pacote em *cache*, o Alpine instala em 1,9 s no aparelho e o Debian em 4,2 s, ocupando 9 MB e 153 MB. No painel, o Worker aparece em 16 s (mediana; de 12 a 19 s), e no pior caso (Debian sem *cache*) em 39 s. Esse tempo é dominado pelo *polling*: a tarefa leva em média 4,5 s para chegar ao Node (IC 95%: 3,0 a 6,0 s; de 0 a 10 s) e o resultado volta no ciclo seguinte. Pelo mesmo motivo, a remoção levou cerca de 20 s em todas as repetições.

**Sobrecarga do PRoot (E3).** Cálculo puro ficou 15% mais lento no Worker e a escrita sequencial praticamente igual (1,0×). Já operações que envolvem caminhos de arquivo pagam caro: criar processos (`fork` + `exec`) ficou 2,7× mais lento, iniciar o interpretador Python, 2,3×, e criar e apagar 1000 arquivos pequenos, **13,4×**. Isso confirma o mecanismo do PRoot (seção 2.4): só as chamadas de sistema com caminhos são interceptadas e traduzidas.

**Latência do terminal (E4).** Em 5 GHz, a mediana foi de 17 ms e o p95 de 58 ms. Em 2,4 GHz, a mediana foi de 45 ms, mas o p95 subiu para 360 ms, acima do critério. O efeito vem do meio sem fio (o `ping` nessa rede já tinha média de 43 ms e pacotes duplicados), não do processamento no aparelho. A medição também revelou um defeito: o agente usava *long-polling* em vez de WebSocket, com p95 de 321 ms e ecos perdidos. Isso foi corrigido antes da rodada final (Figura 5).

![[figuras/e4_latencia_terminal_cdf.png]]

*Figura 5 — Distribuição acumulada da latência de eco do terminal no Node 1.*

**Vazão (E8).** Uma API HTTP simples em Python atendeu cerca de 60 req/s no Worker, contra 137 a 148 req/s no Termux nativo, ou seja, **40% a 45% da vazão nativa** com 10 e 50 conexões. Com uma conexão, a razão foi de 67% (24 contra 36 req/s), limitada pela ida e volta na rede.

**Consumo (E10).** No moto e40, ao longo das 24 h da E7, o agente usou 20 MB de RAM (mediana) e o Supervisor 9,6 MB, e a CPU do DroidServer ficou em 1,6% do aparelho em média. A memória do agente não cresceu ao longo do dia.

**Disponibilidade (E7).** No moto e40, uma API de demonstração rodou de 16/11 às 23:21 a 17/11 às 23:21, com o próprio agente testando o serviço a cada 10 s e gravando o resultado no celular. Assim, a medida não depende do PC: o painel ficou desligado por cerca de 5,3 h sem afetar nada. O resultado foi **99,94%** (8.638 de 8.643 amostras). As 5 falhas são amostras ausentes, em 4 lacunas curtas do registro do próprio agente (a maior de 25 s), contadas como indisponibilidade por um critério conservador. Nenhuma resposta veio com erro, o tempo de resposta teve mediana de 8,9 ms e o PID do serviço foi o mesmo do início ao fim: nem o Supervisor precisou reiniciá-lo, nem o Android o encerrou (Figura 6). Como o `GET` parte do próprio celular, pela interface local, a E7 mede se o processo do serviço continua vivo e respondendo, e não se ele é alcançável pela rede; a latência pela rede é tratada na E4.

![[figuras/e7_disponibilidade.png]]

*Figura 6 — Tempo de resposta da API ao longo das 24 h no Node 2. Os triângulos marcam as amostras ausentes do registro.*
