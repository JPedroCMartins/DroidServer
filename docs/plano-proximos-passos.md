# Plano de próximos passos

Escrito em 15/11/2026 e atualizado em 16/11/2026, com pouco tempo até a entrega. Prioridade: **(1) o sistema funcionando de ponta a ponta numa demonstração, (2) dados medidos para o TCC, (3) texto final.** Tudo o que não serve a esses três itens fica para "trabalhos futuros".

## Onde estamos (16/11, depois da Fase 2B)

| Já funciona (validado nos aparelhos) | Ainda falta |
|---|---|
| `setup.sh`, agente, Host, painel; reboot do celular (Termux:Boot) | Estabilidade por **24 h** de uso (E7 — pendência P1) |
| Cadastro de Nodes pelo painel (varredura + token); troca de IP do celular e do PC | Números da E7 no resumo, na 9.5 e na conclusão (P2) |
| **Dois Nodes** (POCO X6 Pro e moto e40) | Conferir as referências ⚠ (4.5) |
| Criar e remover Worker (Alpine e Debian) pelo painel | |
| Capturas de tela do painel na seção 8.8 (4.6) | |
| **Aba Serviço** (`/app/run.sh`): estado, editor, logs ao vivo, opções, visão geral e ajuda "?" | `.docx` final e revisão do orientador (4.7, 4.8) |
| Aplicações reais respondendo na rede (portas 8080–8082) | |
| Segurança mínima (Fase 2) e painel sem internet | |
| Terminal no navegador, isolamento do `/sdcard`; CPU/RAM em tempo real | |
| Experimentos E1–E5, E8 e E10 com figuras e resultados (nota 09) | |
| 233 testes automatizados | |
| Vault com 13 capítulos, título único, resumo/abstract e conclusão (faltando a E7) | |

---

## ⏸ Pendências — experimentos deixados para depois (16/11)

A pedido do usuário, os experimentos que exigem esperar ficam para depois; primeiro vem o que não depende de tempo (Fase 2B). Celular do projeto: **só o moto e40** (o POCO é pessoal).

| # | Pendência | Depende de |
|---|---|---|
| P1 | 🟡 **E7 — disponibilidade em 24 h** no moto e40 (tela apagada, na tomada), **iniciada em 16/11 às 23:21, termina em 17/11 às 23:21**. A medição é do próprio agente (registro local, vault 8.5.1) e o celular acompanha e calcula sozinho (`~/.config/droidserver/e7/progresso.txt` e `resultado.txt`); o PC e o painel podem ser desligados. Progresso: `DROID_SSH="-p 8022 192.168.1.100" uv run bench/e7_disponibilidade.py --status`; no fim, o mesmo comando sem `--status` gera o CSV oficial. Se o moto reiniciar, `--retomar`. Rodadas anteriores (medidas pelo PC) interrompidas: 1ª por queda de energia (4,42 h, 99,94%) e 2ª pelo usuário (0,23 h, 100%) — dados em `bench/resultados/e7_rodada*` | Deixar o moto 24 h sem mexer |
| P2 | Preencher os `[RESULTADO E7: ...]` do resumo/abstract (nota 00), da 9.5 e da conclusão (11.1 QP3 e 11.2), gerar a figura da E7 (`bench/graficos.py`) e decidir se a H1 fica **confirmada** ou **parcialmente confirmada** | P1 |
| P3 | (Opcional) E7 com o Android em configuração padrão (otimização de bateria ativa), para saber se a condição (c) da H1 é necessária, não só suficiente | P1 + mais 24 h |
| P4 | Regenerar o `.docx` com os números da E7 | P2 |

## Fase 1 — Deixar a demonstração funcionando

Objetivo: na defesa, criar um Worker pelo painel e abrir no navegador um serviço rodando nele.

| # | Tarefa | Por quê |
|---|---|---|
| 1.1 | ✅ *Feito na Fase 1B (aba Serviço).* **Rodar uma aplicação num Worker** (API Flask ou `python -m http.server`) via `/app/run_server.sh` e acessá-la em `http://192.168.1.7:<porta>` | É a promessa central ("VPS no celular"). O PRoot não isola a rede, então a porta do Worker deve abrir direto no IP do celular — **confirmar** |
| 1.2 | ✅ *Substituído pela aba Serviço (editor do `run.sh` + "Inserir exemplo").* Criar um **template de aplicação**: campo opcional "comando de inicialização" no formulário, gravado no `run_server.sh` na criação | Hoje é preciso editar o arquivo pelo terminal; na demonstração isso confunde |
| 1.3 | ~~Testar **Debian e Arch** no aparelho~~ ✅ Debian ok (80 s com `apt`); Arch retirado (sem imagem arm64) | — |
| 1.4 | ✅ *Reboot validado (Termux:Boot); falta o teste de horas de uso (E7).* **Sobreviver a reboot e a horas de uso:** ativar o Termux:Boot, liberar o "Início automático" e o "Sem restrições" de bateria (Xiaomi/HyperOS é agressivo), desativar o *phantom process killer* e reiniciar o celular | Se o agente morrer durante a apresentação, nada funciona |
| 1.5 | ~~Reservar IP fixo no roteador~~ — **desnecessário**: o painel identifica o Node pelo token e acompanha a troca de IP do celular (2.22, validado: .7 → .5); se o PC mudar de IP, basta "Adicionar" o Node de novo (2.27) | Contorna o Node identificado por IP (2.9) sem escrever código |
| 1.6 | Segundo aparelho, **se houver um disponível** | "Cluster" com um nó só enfraquece a defesa |

### Feito além do plano (pedido em 15/11)

- Gráfico em tempo real de CPU do DroidServer e RAM ao lado de cada Node.
- Cadastro de Nodes pelo painel: varredura de rede, pareamento com token, remoção; o `setup.sh` não pergunta mais o IP do Host.
- Campos de pacotes/comando de inicialização: implementados e **retirados** a pedido (a aplicação de demonstração é instalada pelo terminal).

## Fase 1B — Serviço do Worker controlado pelo painel ✅ (feito e validado no aparelho em 16/11)

Objetivo: a pessoa controla **pelo painel** o que roda em cada Worker, **como** e **quando**, e vê os **logs**, sem precisar de terminal nem SSH.

### Como fica para o usuário

Na página do Worker, ao lado da aba **Terminal**, uma aba **Serviço**:

```
┌ Serviço ─────────────────────────────────────────────────────────────┐
│ ● RUNNING  pid 18919 · no ar há 37 min        [■ Parar] [⟳ Reiniciar] │
│ ☑ Iniciar junto com o celular   ☑ Reiniciar automaticamente se cair  │
├ /app/run.sh ─────────────────────────────────────────────────────────┤
│ #!/bin/sh                                                            │
│ cd /app                                                              │
│ exec python3 app.py                                                  │
│                               [Inserir exemplo] [Salvar] [Salvar e reiniciar] │
├ Logs (ao vivo) ────────────────────────── [⏸ Pausar] [Limpar] [Baixar] ┤
│ 23:41:02  [demo] escutando em 0.0.0.0:8080                           │
│ 23:41:09  192.168.1.10 - "GET / HTTP/1.1" 200 -                      │
└──────────────────────────────────────────────────────────────────────┘
```

- **O quê:** o serviço é sempre o arquivo **`/app/run.sh`** do Worker, editável no painel.
- **Como:** botões Iniciar / Parar / Reiniciar; "Salvar e reiniciar" aplica a edição na hora.
- **Quando:** "Iniciar junto com o celular" (padrão: ligado) e "Reiniciar automaticamente se cair" (padrão: ligado).
- **Logs:** saída e erros do serviço ao vivo, com as últimas 200 linhas ao abrir.
- **Ajuda:** sem `run.sh`, o Worker aparece como **"Aguardando /app/run.sh"**. Se o serviço morre logo depois de iniciar, o painel explica a causa mais comum (*"o run.sh terminou; o serviço precisa ficar em primeiro plano, sem `&`"*) e mostra as últimas linhas do log.

### Revisão antes da Fase 2 (16/11)

**Segunda rodada (caça a bugs):** mais cinco problemas corrigidos e validados no aparelho (overview 2.27–2.31): o node não aceitava ser readicionado se o **PC do painel** mudasse de IP; o lançador ignorava o *shebang* do `run.sh` (scripts `#!/bin/bash` ou Python quebravam no Alpine); um **link simbólico** em `/app/run.sh` permitia ler/gravar arquivos do Termux (inclusive o token do pareamento) pela aba Serviço; a aba Serviço apagava limites `DROID_ULIMIT_*` personalizados; e uma falha no `exec` do terminal deixava uma cópia do agente rodando.

**Primeira rodada:**

Teste de ponta a ponta no aparelho (agente 100 testes, Host 59) e pelo painel: Worker Alpine novo criado, `run.sh` com falha (log mostra o motivo), exemplo funcionando, Parar/Iniciar, terminal, gráfico, exclusão limpa. Quatro defeitos encontrados e corrigidos (overview 2.22–2.25): troca de IP não detectada pelo agente, `update` geral do Supervisor reiniciando outros Workers, logs que paravam depois de o agente reiniciar e exemplo que não rodava no Alpine. Fica como pendência o painel depender de CDNs (2.26).

### Recomendações (decididas)

| Decisão | Escolha | Motivo |
|---|---|---|
| Onde fica o serviço | Um arquivo por Worker: `/app/run.sh` | Convenção única e visível; para dois serviços, dois Workers |
| Reiniciar ao editar | **Não** automático: botão "Salvar e reiniciar" | Evita reinício no meio de uma edição; a pessoa decide quando |
| Canal dos comandos e logs | **WebSocket** já existente (Host ↔ Node) | O sync é a cada 10 s; botões e logs precisam responder na hora |
| Quem recebe os logs | Só o navegador que abriu a aba (*room* do Socket.IO) | Já resolve, para esta função, o problema 2.1 da Fase 2 |
| Leitura/escrita do `run.sh` e dos logs | Direto no `rootfs` pelo agente | O rootfs pertence ao Termux; não precisa abrir sessão `proot` |

### Etapas

| # | Tarefa | Onde |
|---|---|---|
| B1 | **Lançador** no lugar do `run_server.sh`: um script interno (`/app/.droidserver/lancador.sh`) que espera o `/app/run.sh` existir, avisa no log enquanto espera e executa o `run.sh` em primeiro plano (`exec`). O Supervisor passa a rodar o lançador; saída e erro num único log com rotação (1 MB × 3) | agente |
| B2 | **Migração dos Workers existentes** ao iniciar o agente: reescreve o `.conf` para o lançador e, se houver um `run_server.sh` personalizado (ex.: `demo_api`), o renomeia para `run.sh`; o script ocioso padrão é descartado | agente |
| B3 | **Comandos do serviço** pelo WebSocket: `iniciar`, `parar`, `reiniciar` (via `supervisorctl`), `ler_script`, `salvar_script` (até 64 KB, gravação atômica, `chmod +x`), `configurar` (liga/desliga `autostart` e `autorestart` no `.conf` + `reread/update`), com resposta de sucesso ou erro | agente + Host |
| B4 | **Logs ao vivo:** ao abrir a aba, o agente manda as últimas 200 linhas e passa a enviar as novas a cada ~1 s enquanto alguém estiver assistindo; para quando ninguém está vendo | agente + Host |
| B5 | **Estado detalhado no sync:** estado do Supervisor, pid, tempo no ar, se o `run.sh` existe, `autostart`/`autorestart` e o motivo da última falha | agente + Host |
| B6 | **Aba Serviço no painel** (layout acima), com o botão "Inserir exemplo" (servidor HTTP simples) e o aviso de erro comum | painel |
| B7 | **Testes** (lançador, migração, comandos, logs, configurações) e **validação no celular**: migrar os 4 Workers, editar o `run.sh` pelo painel, parar/reiniciar, desligar "iniciar com o celular" e reiniciar o aparelho para conferir | todos |
| B8 | **Documentação:** README (seção "Rodando seu serviço"), vault 8.4 (ciclo de vida do serviço) e overview | docs |

Ordem: B1 → B2 → B5 → B3 → B4 → B6 → B7 → B8, com um commit por etapa estável.

### Fora desta fase

Mais de um serviço por Worker, variáveis de ambiente pelo painel, agendamento por horário (cron), upload de arquivos para `/app` e reinício automático ao editar o arquivo.

## Fase 2 — Segurança mínima para não ser questionado ✅ (feito e validado em 16/11)

Feito: 2.5 (painel sem internet), 2.2 (remoção via `POST` + bloqueio de `POST` de outros sites), 2.4 (CORS só da mesma origem), 2.1 (WebSocket do Node autenticado pelo token, terminal e logs por sala, navegador não se passa por Node) e 2.3 (senha `DROID_PANEL_PASSWORD`, sessão de 12 h, chave persistente). Validado no aparelho: um segundo navegador não recebe nada do terminal aberto por outro e uma saída forjada é descartada; login/logout pelo painel; Node sincronizando normalmente com a senha ativa. Testes: 73 no Host, 107 no agente. **Para a defesa:** suba o Host com `DROID_PANEL_PASSWORD` definida.

Corrigir só o que uma banca aponta em 1 minuto. O resto vai para as limitações.

| # | Tarefa | Item |
|---|---|---|
| 2.1 | Terminal enviado só para quem o abriu (*rooms* do Socket.IO por sessão e por Node) | 2.7 |
| 2.2 | Remoção via `POST` em vez de `GET` | 2.8 |
| 2.3 | Senha única no painel (`DROID_PANEL_PASSWORD`, login simples com sessão) | 1.2 |
| 2.4 | Restringir o CORS à origem do próprio painel | 2.10 |
| 2.5 | **Painel funcionando sem internet:** servir Tailwind, xterm.js, Socket.IO e a fonte a partir de `static/` (hoje vêm de CDNs) | 2.26 |

A 2.5 entrou na revisão de 16/11: numa rede de laboratório sem internet, o painel não abre. É barata e protege a demonstração.

## Fase 3 — Dados para o TCC 🟡 (16/11: E1–E5, E8 e E10 feitos; E7 pendente — ver Pendências)

> **16/11, 18:37:** uma queda de energia desligou o PC (e com ele o Host e o *script* da E7) depois de 4,4 h de medição (rodada 1, 99,9%, guardada em `bench/resultados/e7_rodada1_interrompida_*.csv`). O moto e40 seguiu na bateria e o serviço **não reiniciou** (6 h no ar). A E7 foi reiniciada às 20:22 (rodada 2, 24 h).

**Feito em 16/11** (resultados na nota 09, seção 9.5; *scripts* e CSVs em `bench/`): E1/E2/E5 (20 criações, Alpine e Debian, com e sem cache), E3 (10 repetições), E4 (1000 medições em 5 GHz com *polling*, 5 GHz com WebSocket e 2,4 GHz), E8 (Worker × nativo, 1/10/50 conexões) e E10 parcial. Um **segundo Node** (moto e40, Android 11) foi adicionado ao cluster, o que também cumpre a 1.6. A E7 roda no moto e40 desde 14:11; pode ser encerrada depois de uma noite com a tela apagada (`--resumo` funciona com dados parciais). Defeitos achados nas medições: 2.32–2.34 do overview.

Do protocolo da nota 09, executar **só o essencial**, com scripts no repositório (`bench/`) e dados brutos em CSV:

| # | Experimento | Questão | Como |
|---|---|---|---|
| 3.1 | **E1** — Tempo de provisionamento (Alpine e Debian; 5 repetições cada, com e sem cache) | QP1 | Script no PC que usa a API (`/deploy_worker` → espera `RUNNING` → remove) |
| 3.2 | **E3** — Sobrecarga do PRoot: o mesmo benchmark no Termux nativo e dentro do Worker (CPU, E/S de arquivos, instalação de pacote) | QP1 | Script no celular, via SSH |
| 3.3 | **E4** — Latência do terminal (eco de 1 tecla, 500 amostras; mediana e p95) | QP2 | Cliente Socket.IO em Python no PC, sem navegador |
| 3.4 | **E7** — Disponibilidade em 24 h: o Host faz `GET` na aplicação do Worker a cada 10 s e registra falhas, reinícios, CPU e RAM | QP3 / H1 | Script em segundo plano no PC; deixar rodando de noite |
| 3.5 | **E8** — Vazão da aplicação (`hey` ou `wrk`) com a CPU do Worker | QP3 | No PC |

Ficam de fora, citados como limitação: E6 (detecção de falha), E9 (temperatura e energia, que exigem Termux:API ou medidor USB) e o consumo de energia.

## Fase 2B — Aba Serviço mais amigável ✅ (abordagem A, feita e validada no moto e40 em 16/11)

Objetivo: quem abre a aba Serviço entende, sem README nem terminal, **o que roda, se está funcionando, onde acessar e o que fazer quando falha** — e consegue pôr uma aplicação no ar pelo painel (útil na demonstração para a banca). Proposta completa, com telas e alternativas: [`docs/superpowers/specs/2026-11-16-aba-servico-amigavel-design.md`](superpowers/specs/2026-11-16-aba-servico-amigavel-design.md).

**Abordagens** (escolhida: **A** — ajuda + visão geral; B e C ficam registradas)

| | Abordagem | Para o usuário | Custo |
|---|---|---|---|
| A | Ajuda "?" + tela de informações | Continua escrevendo o `run.sh`, mas com guia, exemplos e mais dados na tela | Baixo |
| **B** | **Assistente que gera o `run.sh`** (+ A) | Escolhe o tipo de aplicação e preenche porta/pasta/pacotes/comando; o painel gera o script, editável | Médio |
| C | Configuração estruturada, sem shell (estilo Procfile) | Só formulário; o agente monta o processo | Alto, cria um segundo formato |

**Etapas** (versão A; S4 removida)

| # | Tarefa | Onde |
|---|---|---|
| S1 | ✅ **"?" com guia** em painel lateral: passo a passo (arquivos em `/app` → pacotes → `run.sh` → porta → salvar e reiniciar), regras do script, exemplos por tipo, erros comuns, significado de cada estado; "?" também nas opções | painel |
| S2 | ✅ **Visão geral**: endereço `http://<ip>:<porta>` com "Abrir" e "Testar" (GET a partir do Host), reinícios do dia e última falha, CPU/RAM do serviço, disco do Worker, distribuição, último salvamento; botões habilitados conforme o estado | painel + Host + agente |
| S3 | ✅ **Dados no agente**: porta/tipo lidos do cabeçalho do `run.sh` (`# droidserver: porta=8080`), RAM somando a árvore de processos, contagem de reinícios pelo log, `du` em segundo plano com cache de 10 min | agente |
| ~~S4~~ | ~~Assistente~~ — fora desta fase (vai para trabalhos futuros, com o CI/CD) | — |
| S5 | ✅ Editor com números de linha e layout em blocos (Visão geral · run.sh · Logs) | painel |
| S6 | ✅ Testes + validação no aparelho + README/vault (8.4.1) | todos |

Restrição verificada: sem *root*, o Android nega `/proc/net/tcp`, então **a porta não pode ser descoberta automaticamente** e precisa ser informada (assistente ou cabeçalho do script). O projeto usa **só o moto e40** (o POCO é o celular pessoal do usuário). Com a E7 adiada, o moto está livre para validar esta fase.

**Decisões** (16/11, usuário): abordagem **A**; repositório Git fica para uma futura **integração de CI/CD** (seção 10.3 do TCC), e as variáveis de ambiente vão junto. A porta é declarada num cabeçalho do `run.sh` (`# droidserver: porta=8080`). Perguntas originais, já respondidas:
1. Abordagem: B (recomendada), só A ou C?
2. Como o código chega ao `/app` sem terminal: campo "repositório Git" no assistente (barato) ou envio de arquivos pelo painel (caro)?
3. Variáveis de ambiente (ex.: *token* de bot) num campo próprio, fora do script e dos logs, ou ficam no script por enquanto?
4. Tipos no assistente: site estático, API Python, Node.js, bot/script Python e comando livre — falta algum?
5. Para a defesa, a prioridade é a ajuda + informações (rápido) ou o assistente completo?

## Fase 4 — Fechar o texto

| # | Tarefa |
|---|---|
| 4.1 | ✅ *Feito em 16/11:* "DroidServer: orquestração de servidores virtuais privados em smartphones Android reaproveitados" (capa, folha de rosto, vault, README; termo definido na seção 1.1) |
| 4.2 | 🟡 *16/11:* Capítulo 9.5 (Resultados) escrito com tabelas e gráficos de E1, E3, E4 e E8; falta a E7 |
| 4.3 | ✅ *16/11:* Resumo/Abstract (nota 00) preenchidos com os números reais (226/216 palavras); falta o valor da E7 |
| 4.4 | ✅ *16/11:* Conclusão (nota 11) responde QP1–QP3 e discute a H1; falta fechar com a E7 |
| 4.5 | Conferir as referências marcadas com ⚠ e ler na íntegra Switzer et al. (2023), Shahrad e Wentzlaff (2017) e Büsching et al. (2012) |
| 4.6 | ✅ *16/11:* seção 8.8 com as Figuras 5–9 (Dashboard com gráfico, Node, aba Serviço, ajuda, terminal), geradas por `bench/capturas_tela.py` no moto e40 |
| 4.7 | 🟡 *16/11: versão inicial gerada automaticamente do vault* — `docs/DroidServer_TCC_artigo.docx` (ABNT: capa, folha de rosto, resumo/abstract, seções 1–10, referências, glossário; figuras e quadros numerados com título acima e fonte abaixo; lacunas em amarelo). Regenerar com `cd docs/gerador-docx && npm install && npm run gerar`. Falta: modelo oficial da Uninorte (se houver), nome do orientador e revisão final |
| 4.8 | Revisão do orientador |

## Fora do escopo (vai para "trabalhos futuros")

Escalonador automático, persistência do Host (SQLite), UUID por Node, proxy reverso, TLS, imagens prontas de Worker, comparação com Raspberry Pi, cálculo de carbono (CCI) e qualquer refatoração do `index.html`.

## Ordem sugerida (atualizada em 16/11)

Primeiro o que não depende de esperar; os experimentos ficam como pendências (P1–P4, no topo).

```
Agora       ✅ 4.6 capturas de tela → ✅ registro local no Node → iniciar P1 (E7, 24 h com o moto parado; PC pode desligar)
Durante a E7  4.5 referências ⚠ → enxugar o texto
Depois      P2 → P4 → .docx final (4.7) → orientador
```

A E7 é o caminho crítico (P2, P4, 4.7 e 4.8 dependem dela): iniciar assim que as capturas estiverem prontas e fazer 4.5 e o texto enquanto ela roda. Se o prazo apertar, corte P3. **Não corte** a E7 (P1): é a evidência da H1.

## Riscos

| Risco | Mitigação |
|---|---|
| HyperOS ou Android 16 mata o Termux em segundo plano | Fazer 1.4 cedo; se não houver solução, deixar o celular na tela do Termux durante a demo e registrar como resultado (é um achado relevante para a QP3) |
| A rede da faculdade isola os dispositivos no Wi-Fi | Levar um roteador próprio ou usar o roteador do celular do Host (*hotspot*) na defesa |
| Sem internet no local da defesa | 2.5 (painel com arquivos locais); o `apk`/`apt` também precisa de internet: deixar os Workers da demo com os pacotes já instalados |
| O IP do celular ou do PC muda na hora (DHCP) | O painel acompanha o celular sozinho; se o PC mudar, "Adicionar" o Node de novo. Ensaiar uma vez antes |
| Um único aparelho | ✅ Resolvido: dois Nodes (POCO X6 Pro e moto e40) |
| Queda de energia (aconteceu em 16/11) | O Host é só gerenciamento: os celulares seguem na bateria, os serviços não caem e as métricas continuam no registro de cada celular (16/11); só o painel some. Na defesa, ligar o PC num *nobreak* ou usar um notebook com bateria |
