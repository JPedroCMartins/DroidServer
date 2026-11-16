# 9. Protocolo de Avaliação Experimental

> [!warning] Ainda não executado
> A metodologia classifica a pesquisa como experimental, mas o repositório ainda não contém medições. Este capítulo define **o que medir, como e com quais critérios**, para que os resultados sejam reprodutíveis (JAIN, 1991). Preencha as tabelas à medida que os experimentos forem executados.

## 9.1 Ambiente de testes

| Item | Descrição (preencher) |
|---|---|
| Host | CPU, RAM, SO (Debian x.y), Python 3.12 |
| Rede | Roteador, padrão Wi-Fi (2,4/5 GHz), distância dos aparelhos |
| Node 1 | Modelo, SoC, RAM, versão do Android, estado da bateria/tela |
| Node 2 | … |
| Node 3 | … |
| Termux / proot-distro | Versões |
| Configuração Android | Otimização de bateria desativada? *Phantom process killer* desativado? Wake-lock? |

Recomenda-se ao menos três aparelhos de gerações diferentes (ex.: 2016, 2019, 2022) para observar a heterogeneidade.

## 9.2 Experimentos

| ID | Questão | Métrica | Procedimento | Repetições |
|---|---|---|---|---|
| E1 | QP1 | **Tempo de provisionamento** por distribuição (s) | Criar Workers Alpine, Debian e Arch pelo painel; medir do clique até `RUNNING` (instrumentar `ts` da tarefa e do resultado) | 10 por distro × Node |
| E2 | QP1 | **Uso de disco** por Worker (MB) | `du -sh` do *rootfs* após a criação | 1 por distro |
| E3 | QP1 | **Sobrecarga do PRoot** (%) | Rodar o mesmo *benchmark* no Termux nativo e dentro do Worker: CPU (`sysbench cpu`), E/S de arquivos (`sysbench fileio` ou `fio`), chamadas de sistema (compilar um projeto pequeno; `apk add`/`apt install` de um pacote) | 10 cada |
| E4 | QP2 | **Latência de eco do terminal** (ms) | Enviar um caractere e medir o tempo até o eco voltar ao navegador (instrumentar o JS com `performance.now()`) | 1000 amostras; reportar mediana, p95, p99 |
| E5 | QP2 | **Latência de entrega de tarefa** (s) | Tempo entre o enfileiramento no Host e o início da execução no Node; esperado ≈ U(0, 10 s) | 50 |
| E6 | QP2 | **Tempo de detecção de falha** (s) e falsos positivos | Desligar o Wi-Fi do Node e medir até o painel mostrar *Offline*; contar transições *Offline* indevidas em 24 h | 20 / 24 h |
| E7 | QP3 | **Disponibilidade** (%) | Worker com um servidor HTTP simples; um *script* no Host faz `GET` a cada 10 s por 24–72 h; disponibilidade = respostas OK / total. Registrar cada `signal 9` e reinício | 1 rodada por configuração |
| E8 | QP3 | **Vazão de um microsserviço** (req/s) e CPU do Worker (`cpu_workers`) | `wrk` ou `hey` contra uma API leve (Flask/FastAPI ou Go) no Worker; comparar com o mesmo serviço em uma VPS básica ou num Raspberry Pi, se disponível | 5 |
| E9 | QP3 | **Temperatura e energia** | Ler `/sys/class/thermal/*/temp` e `/sys/class/power_supply/battery/*` (quando acessíveis) ou usar um medidor USB na tomada, em repouso e sob carga E8 | Contínuo durante E7/E8 |
| E10 | QP3 | **Consumo do agente** | CPU (métrica `cpu_termux` com os Workers parados) e RSS do `node.py` e do `supervisord` em repouso | 1 h |

### Fatores e configurações para E7

Compare pelo menos duas configurações para sustentar a hipótese H1:

1. Android padrão (otimização de bateria ativa, sem *wake-lock*);
2. Otimização de bateria desativada para o Termux + `termux-wake-lock` + *phantom process killer* desativado (Android 12+).

## 9.3 Critérios de aceitação (proposta — validar com o orientador)

| Critério | Limite |
|---|---|
| Disponibilidade do Worker em 24 h (configuração 2) | ≥ 99% |
| Latência de eco do terminal, p95, em LAN | ≤ 200 ms |
| Detecção de Node *offline* | ≤ 35 s |
| Provisionamento de Worker Alpine | ≤ 2 min |

## 9.4 Análise

Reportar média, desvio-padrão e intervalo de confiança de 95% (ou mediana e percentis para latências, que costumam ter distribuição assimétrica). Gráficos sugeridos: *boxplot* do tempo de provisionamento por distribuição; CDF da latência do terminal; linha do tempo de disponibilidade com os eventos de reinício; barras de sobrecarga do PRoot por tipo de carga.

## 9.5 Resultados

*(Preencher.)*
