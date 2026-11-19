# 9. Avaliação Experimental

> [!info] Executado de 16 a 17/11/2026
> Os *scripts* e os dados brutos (CSV) estão em `bench/` no repositório; as figuras são geradas por `bench/graficos.py`.

## 9.1 Ambiente e experimentos

O Host foi um PC Debian 13 (Xeon E5-2620 v3, 39 GB de RAM), ligado ao roteador por cabo. Os Nodes ficaram no Wi-Fi 2,4 GHz, na tomada, com a otimização de bateria desativada para o Termux e `termux-wake-lock` ativo. O **Node 1** foi um Xiaomi POCO X6 Pro (Dimensity 8300, 7,3 GB, Android 16), e o **Node 2**, um Motorola moto e40 (Unisoc T700, 3,4 GB, Android 11). Os Workers usaram Alpine 3.24 e Debian 13.

| ID | QP | Métrica |
|---|---|---|
| E1, E2, E5 | QP1/QP2 | Tempo de provisionamento, disco por Worker e atraso de entrega da tarefa |
| E3 | QP1 | Sobrecarga do PRoot em relação ao Termux nativo |
| E4 | QP2 | Latência de eco do terminal (1000 medições) |
| E7 | QP3 | Disponibilidade de uma API em 24 h |
| E8 | QP3 | Vazão de uma API HTTP leve |
| E10 | QP3 | Consumo do próprio DroidServer |

*Quadro 3 — Experimentos realizados. Fonte: elaborado pelo autor.*

Para tempos, usou-se a média com IC de 95%, e para latências e vazão, a mediana e os percentis, por terem distribuição assimétrica (JAIN, 1991). Os critérios de aceitação estão na Tabela 9.1. A medição de temperatura e energia (E9) não foi possível, porque o Android 16 nega a leitura dos sensores sem *root*. O tempo de detecção de falha (E6) não foi medido à parte.

## 9.2 Resultados

| Critério | Limite | Resultado |
|---|---|---|
| Disponibilidade do Worker em 24 h | ≥ 99% | ✅ 99,94%, sem reinícios do serviço |
| Latência de eco do terminal, p95, em LAN | ≤ 200 ms | ✅ 58 ms em 5 GHz · ❌ 360 ms em 2,4 GHz |
| Detecção de Node *offline* | ≤ 35 s | ✅ por construção: 25 s sem *sync* + até 10 s de atualização |
| Provisionamento de Worker Alpine | ≤ 2 min | ✅ 1,9 s no aparelho; 16 s (mediana) no painel |

*Tabela 9.1 — Critérios de aceitação e resultados. Fonte: elaborado pelo autor.*

**Provisionamento (E1, E2, E5).** As 20 criações e remoções deram certo. Com o pacote em *cache*, o Alpine instala em 1,9 s no aparelho e o Debian em 4,2 s, ocupando 9 MB e 153 MB. No painel, o Worker aparece em 16 s (mediana), e no pior caso (Debian sem *cache*) em 39 s. Esse tempo é dominado pelo *polling*: a tarefa leva em média 4,5 s para chegar ao Node (de 0 a 10 s) e o resultado volta no ciclo seguinte.

**Sobrecarga do PRoot (E3).** Cálculo puro ficou 15% mais lento no Worker e a escrita sequencial praticamente igual (1,0×). Já operações que envolvem caminhos de arquivo pagam caro: criar processos (`fork` + `exec`) ficou 2,7× mais lento, e criar e apagar 1000 arquivos pequenos, **13,4×**. Isso confirma o mecanismo do PRoot (seção 5.4): só as chamadas de sistema com caminhos são interceptadas e traduzidas. Serviços de rede e de CPU sofrem pouco, e compilação e instalação de pacotes, mais.

**Latência do terminal (E4).** Em 5 GHz, a mediana foi de 17 ms e o p95 de 58 ms. Em 2,4 GHz, a mediana foi de 45 ms, mas o p95 subiu para 360 ms, acima do critério. O efeito vem do meio sem fio (o `ping` nessa rede já tinha média de 43 ms e pacotes duplicados), não do sistema. A medição também revelou um defeito: o agente usava *long-polling* em vez de WebSocket, com p95 de 321 ms e ecos perdidos. Isso foi corrigido antes da rodada final (Figura 9.1).

![[figuras/e4_latencia_terminal_cdf.png]]

*Figura 9.1 — Distribuição acumulada da latência de eco do terminal.*

**Vazão (E8).** Uma API HTTP simples em Python atendeu cerca de 60 req/s no Worker, contra 137 a 148 req/s no Termux nativo, ou seja, **40% a 45% da vazão nativa** com concorrência. Para uso pessoal ou de laboratório, isso basta. Cargas maiores precisariam rodar fora do PRoot ou em vários Nodes.

**Consumo (E10).** No moto e40, ao longo de 24 h, o agente usou 20 MB de RAM (mediana) e o Supervisor 9,6 MB, e a CPU do DroidServer ficou em 1,6% do aparelho em média. A memória do agente não cresceu ao longo do dia.

**Disponibilidade (E7).** No moto e40, uma API de demonstração rodou de 16/11 às 23:21 a 17/11 às 23:21, com o próprio agente testando o serviço a cada 10 s e gravando o resultado no celular. Assim, a medida não depende do PC: o painel ficou desligado por cerca de 5,3 h sem afetar nada. O resultado foi **99,94%** (8.638 de 8.643 amostras), e as 5 falhas são lacunas curtas no registro do próprio agente, a maior de 25 s, contadas como indisponibilidade por um critério conservador. Nenhuma resposta veio com erro, o tempo de resposta teve mediana de 8,9 ms e o PID do serviço foi o mesmo do início ao fim: nem o Supervisor precisou reiniciá-lo, nem o Android o encerrou (Figura 9.2). Uma rodada anterior, de 4,4 h, foi interrompida por uma queda de energia no PC, e o serviço seguiu no ar no celular, que passou a usar a bateria.

![[figuras/e7_disponibilidade.png]]

*Figura 9.2 — Tempo de resposta da API ao longo das 24 h; os triângulos marcam as amostras sem resposta.*
