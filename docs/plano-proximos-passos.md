# Plano de próximos passos

Escrito em 15/11/2026, com pouco tempo até a entrega. Prioridade: **(1) o sistema funcionando de ponta a ponta numa demonstração, (2) dados medidos para o TCC, (3) texto final.** Tudo o que não serve a esses três itens fica para "trabalhos futuros".

## Onde estamos

| Já funciona (validado no Xiaomi, Android 16) | Ainda não testado ou não existe |
|---|---|
| `setup.sh`, agente, Host, painel | Rodar uma **aplicação real** num Worker e acessá-la pela rede |
| Criar e remover Worker (Alpine) pelo painel | Debian e Arch no aparelho |
| Terminal no navegador, isolamento do `/sdcard` | Mais de um Node (cluster de verdade) |
| CPU do DroidServer (total e por Worker), RAM | Estabilidade por horas, **reboot** do celular |
| 93 testes automatizados | Nenhum experimento da nota 09 executado |
| Vault com 12 capítulos e ~45 referências | Resultados, resumo, título único, documento ABNT final |

---

## Fase 1 — Deixar a demonstração funcionando (≈ 2 dias)

Objetivo: na defesa, criar um Worker pelo painel e abrir no navegador um serviço rodando nele.

| # | Tarefa | Por quê | Esforço |
|---|---|---|---|
| 1.1 | **Rodar uma aplicação num Worker** (API Flask ou `python -m http.server`) via `/app/run_server.sh` e acessá-la em `http://192.168.1.7:<porta>` | É a promessa central ("VPS no celular"). O PRoot não isola a rede, então a porta do Worker deve abrir direto no IP do celular — **confirmar** | 2 h |
| 1.2 | Criar um **template de aplicação**: campo opcional "comando de inicialização" no formulário, gravado no `run_server.sh` na criação | Hoje é preciso editar o arquivo pelo terminal; na demonstração isso confunde | 3 h |
| 1.3 | Testar **Debian e Arch** no aparelho | O painel oferece as três distribuições; só a Alpine foi testada | 1 h |
| 1.4 | **Sobreviver a reboot e a horas de uso:** ativar o Termux:Boot, liberar o "Início automático" e o "Sem restrições" de bateria (Xiaomi/HyperOS é agressivo), desativar o *phantom process killer* e reiniciar o celular | Se o agente morrer durante a apresentação, nada funciona | 2 h |
| 1.5 | **Reservar IP fixo** para o(s) celular(es) no roteador (DHCP *reservation*) | Contorna o Node identificado por IP (2.9) sem escrever código | 15 min |
| 1.6 | Segundo aparelho, **se houver um disponível** | "Cluster" com um nó só enfraquece a defesa | 1 h |

## Fase 2 — Segurança mínima para não ser questionado (≈ 1 dia)

Corrigir só o que uma banca aponta em 1 minuto. O resto vai para as limitações.

| # | Tarefa | Item | Esforço |
|---|---|---|---|
| 2.1 | Terminal enviado só para quem o abriu (*rooms* do Socket.IO por sessão e por Node) | 2.7 | 2 h |
| 2.2 | Remoção via `POST` em vez de `GET` | 2.8 | 30 min |
| 2.3 | Senha única no painel (`DROID_PANEL_PASSWORD`, login simples com sessão) | 1.2 | 2 h |
| 2.4 | Restringir o CORS à origem do próprio painel | 2.10 | 15 min |

## Fase 3 — Dados para o TCC (≈ 3 dias, metade é o aparelho trabalhando sozinho)

Do protocolo da nota 09, executar **só o essencial**, com scripts no repositório (`bench/`) e dados brutos em CSV:

| # | Experimento | Questão | Como | Esforço |
|---|---|---|---|---|
| 3.1 | **E1** — Tempo de provisionamento (Alpine, Debian, Arch; 5 repetições cada, com e sem cache) | QP1 | Script no PC que usa a API (`/deploy_worker` → espera `RUNNING` → remove) | 3 h + execução |
| 3.2 | **E3** — Sobrecarga do PRoot: o mesmo benchmark no Termux nativo e dentro do Worker (CPU, E/S de arquivos, instalação de pacote) | QP1 | Script no celular, via SSH | 3 h |
| 3.3 | **E4** — Latência do terminal (eco de 1 tecla, 500 amostras; mediana e p95) | QP2 | Cliente Socket.IO em Python no PC, sem navegador | 3 h |
| 3.4 | **E7** — Disponibilidade em 24 h: o Host faz `GET` na aplicação do Worker a cada 10 s e registra falhas, reinícios, CPU e RAM | QP3 / H1 | Script em segundo plano no PC; deixar rodando de noite | 2 h + 24 h |
| 3.5 | **E8** — Vazão da aplicação (`hey` ou `wrk`) com a CPU do Worker | QP3 | No PC | 1 h |

Ficam de fora, citados como limitação: E6 (detecção de falha), E9 (temperatura e energia, que exigem Termux:API ou medidor USB) e o consumo de energia.

## Fase 4 — Fechar o texto (≈ 3 dias)

| # | Tarefa | Esforço |
|---|---|---|
| 4.1 | **Escolher um único título** e aplicar na capa, no vault e no README | 15 min |
| 4.2 | Escrever o capítulo 9.5 (Resultados) com tabelas e gráficos da Fase 3 | 1 dia |
| 4.3 | Preencher o Resumo/Abstract (nota 00) com os números reais | 1 h |
| 4.4 | Conclusão: responder às QP1–QP3 e dizer se a hipótese H1 foi confirmada | 3 h |
| 4.5 | Conferir as referências marcadas com ⚠ e ler na íntegra Switzer et al. (2023), Shahrad e Wentzlaff (2017) e Büsching et al. (2012) | 4 h |
| 4.6 | Capturas de tela para a seção 8.8 (Dashboard, Node, terminal, CPU por Worker) | 30 min |
| 4.7 | Gerar o documento ABNT: instalar Pandoc e converter o vault para `.odt`/`.docx` com o modelo da Uninorte, ou colar no `.odt` existente | 4 h |
| 4.8 | Revisão do orientador | — |

## Fora do escopo (vai para "trabalhos futuros")

Escalonador automático, persistência do Host (SQLite), UUID por Node, proxy reverso, TLS, imagens prontas de Worker, comparação com Raspberry Pi, cálculo de carbono (CCI) e qualquer refatoração do `index.html`.

## Ordem sugerida

```
Dia 1   1.1 → 1.3 → 1.5 → 1.4 (inclui reboot)        ← demo funcionando
Dia 2   1.2 → 2.1 → 2.2 → 2.4 → 2.3                  ← demo apresentável
Dia 3   scripts 3.1, 3.3, 3.4 → iniciar E7 (24 h)    ← dados rodando de noite
Dia 4   3.2, 3.5, 3.1 executado → git push            ← dados completos
Dia 5   4.1, 4.2, 4.6                                 ← resultados
Dia 6   4.3, 4.4, 4.5                                 ← texto fechado
Dia 7   4.7 + folga para imprevistos → orientador
```

Se o prazo for mais curto, corte nesta ordem: 2.3 → 1.6 → 3.5 → 3.2 → 1.2. **Não corte** 1.1, 1.4, 3.4 nem 4.2: sem eles não há demo nem resultado.

## Riscos

| Risco | Mitigação |
|---|---|
| HyperOS ou Android 16 mata o Termux em segundo plano | Fazer 1.4 cedo; se não houver solução, deixar o celular na tela do Termux durante a demo e registrar como resultado (é um achado relevante para a QP3) |
| A rede da faculdade isola os dispositivos no Wi-Fi | Levar um roteador próprio ou usar o roteador do celular do Host (*hotspot*) na defesa |
| Debian ou Arch falham no `proot-distro` do Android 16 | Documentar como resultado e demonstrar com Alpine |
| Um único aparelho | Assumir explicitamente como limitação ("prova de conceito com 1 nó") |
