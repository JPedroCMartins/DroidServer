# Plano de próximos passos

Escrito em 15/11/2026 e atualizado em 16/11/2026, com pouco tempo até a entrega. Prioridade: **(1) o sistema funcionando de ponta a ponta numa demonstração, (2) dados medidos para o TCC, (3) texto final.** Tudo o que não serve a esses três itens fica para "trabalhos futuros".

## Onde estamos (16/11)

| Já funciona (validado no Xiaomi, Android 16) | Ainda não testado ou não existe |
|---|---|
| `setup.sh`, agente, Host, painel; reboot do celular (Termux:Boot) | Estabilidade por **horas** de uso (E7) |
| Cadastro de Nodes pelo painel (varredura + token); troca de IP do celular e do PC | Mais de um Node (cluster de verdade) |
| Criar e remover Worker (Alpine e Debian) pelo painel | Painel **sem internet** (depende de CDNs, 2.26) |
| **Serviço do Worker** (`/app/run.sh`) com estado, editor, logs ao vivo e opções | Segurança mínima (Fase 2) |
| Aplicações reais respondendo na rede (portas 8080–8082) | Nenhum experimento da nota 09 executado |
| Terminal no navegador, isolamento do `/sdcard` | Resultados, resumo, título único, documento ABNT final |
| CPU do DroidServer (total e por Worker), RAM, gráfico em tempo real | |
| 166 testes automatizados (60 no Host, 106 no agente) | |
| Vault com 12 capítulos e ~45 referências | |

---|---|
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
| 1.1 | ✅ *Feito na Fase 1B (aba Serviço).* **Rodar uma aplicação num Worker** (API Flask ou `python -m http.server`) via `/app/run_server.sh` e acessá-la em `http://192.168.1.7:<porta>` | É a promessa central ("VPS no celular"). O PRoot não isola a rede, então a porta do Worker deve abrir direto no IP do celular — **confirmar** | 2 h |
| 1.2 | ✅ *Substituído pela aba Serviço (editor do `run.sh` + "Inserir exemplo").* Criar um **template de aplicação**: campo opcional "comando de inicialização" no formulário, gravado no `run_server.sh` na criação | Hoje é preciso editar o arquivo pelo terminal; na demonstração isso confunde | 3 h |
| 1.3 | ~~Testar **Debian e Arch** no aparelho~~ ✅ Debian ok (80 s com `apt`); Arch retirado (sem imagem arm64) | — | feito |
| 1.4 | ✅ *Reboot validado (Termux:Boot); falta o teste de horas de uso (E7).* **Sobreviver a reboot e a horas de uso:** ativar o Termux:Boot, liberar o "Início automático" e o "Sem restrições" de bateria (Xiaomi/HyperOS é agressivo), desativar o *phantom process killer* e reiniciar o celular | Se o agente morrer durante a apresentação, nada funciona | 2 h |
| 1.5 | ~~Reservar IP fixo no roteador~~ — **desnecessário**: o painel identifica o Node pelo token e acompanha a troca de IP do celular (2.22, validado: .7 → .5); se o PC mudar de IP, basta "Adicionar" o Node de novo (2.27) | Contorna o Node identificado por IP (2.9) sem escrever código | 15 min |
| 1.6 | Segundo aparelho, **se houver um disponível** | "Cluster" com um nó só enfraquece a defesa | 1 h |

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

| # | Tarefa | Onde | Esforço |
|---|---|---|---|
| B1 | **Lançador** no lugar do `run_server.sh`: um script interno (`/app/.droidserver/lancador.sh`) que espera o `/app/run.sh` existir, avisa no log enquanto espera e executa o `run.sh` em primeiro plano (`exec`). O Supervisor passa a rodar o lançador; saída e erro num único log com rotação (1 MB × 3) | agente | 1 h |
| B2 | **Migração dos Workers existentes** ao iniciar o agente: reescreve o `.conf` para o lançador e, se houver um `run_server.sh` personalizado (ex.: `demo_api`), o renomeia para `run.sh`; o script ocioso padrão é descartado | agente | 45 min |
| B3 | **Comandos do serviço** pelo WebSocket: `iniciar`, `parar`, `reiniciar` (via `supervisorctl`), `ler_script`, `salvar_script` (até 64 KB, gravação atômica, `chmod +x`), `configurar` (liga/desliga `autostart` e `autorestart` no `.conf` + `reread/update`), com resposta de sucesso ou erro | agente + Host | 2 h |
| B4 | **Logs ao vivo:** ao abrir a aba, o agente manda as últimas 200 linhas e passa a enviar as novas a cada ~1 s enquanto alguém estiver assistindo; para quando ninguém está vendo | agente + Host | 1,5 h |
| B5 | **Estado detalhado no sync:** estado do Supervisor, pid, tempo no ar, se o `run.sh` existe, `autostart`/`autorestart` e o motivo da última falha | agente + Host | 45 min |
| B6 | **Aba Serviço no painel** (layout acima), com o botão "Inserir exemplo" (servidor HTTP simples) e o aviso de erro comum | painel | 2 h |
| B7 | **Testes** (lançador, migração, comandos, logs, configurações) e **validação no celular**: migrar os 4 Workers, editar o `run.sh` pelo painel, parar/reiniciar, desligar "iniciar com o celular" e reiniciar o aparelho para conferir | todos | 1,5 h |
| B8 | **Documentação:** README (seção "Rodando seu serviço"), vault 8.4 (ciclo de vida do serviço) e overview | docs | 45 min |

**Total: ≈ 10 h.** Ordem: B1 → B2 → B5 → B3 → B4 → B6 → B7 → B8, com um commit por etapa estável.

### Fora desta fase

Mais de um serviço por Worker, variáveis de ambiente pelo painel, agendamento por horário (cron), upload de arquivos para `/app` e reinício automático ao editar o arquivo.

## Fase 2 — Segurança mínima para não ser questionado ✅ (feito e validado em 16/11)

Feito: 2.5 (painel sem internet), 2.2 (remoção via `POST` + bloqueio de `POST` de outros sites), 2.4 (CORS só da mesma origem), 2.1 (WebSocket do Node autenticado pelo token, terminal e logs por sala, navegador não se passa por Node) e 2.3 (senha `DROID_PANEL_PASSWORD`, sessão de 12 h, chave persistente). Validado no aparelho: um segundo navegador não recebe nada do terminal aberto por outro e uma saída forjada é descartada; login/logout pelo painel; Node sincronizando normalmente com a senha ativa. Testes: 73 no Host, 107 no agente. **Para a defesa:** suba o Host com `DROID_PANEL_PASSWORD` definida.

Corrigir só o que uma banca aponta em 1 minuto. O resto vai para as limitações.

| # | Tarefa | Item | Esforço |
|---|---|---|---|
| 2.1 | Terminal enviado só para quem o abriu (*rooms* do Socket.IO por sessão e por Node) | 2.7 | 2 h |
| 2.2 | Remoção via `POST` em vez de `GET` | 2.8 | 30 min |
| 2.3 | Senha única no painel (`DROID_PANEL_PASSWORD`, login simples com sessão) | 1.2 | 2 h |
| 2.4 | Restringir o CORS à origem do próprio painel | 2.10 | 15 min |
| 2.5 | **Painel funcionando sem internet:** servir Tailwind, xterm.js, Socket.IO e a fonte a partir de `static/` (hoje vêm de CDNs) | 2.26 | 1 h |

A 2.5 entrou na revisão de 16/11: numa rede de laboratório sem internet, o painel não abre. É barata e protege a demonstração.

## Fase 3 — Dados para o TCC (≈ 3 dias, metade é o aparelho trabalhando sozinho)

Do protocolo da nota 09, executar **só o essencial**, com scripts no repositório (`bench/`) e dados brutos em CSV:

| # | Experimento | Questão | Como | Esforço |
|---|---|---|---|---|
| 3.1 | **E1** — Tempo de provisionamento (Alpine e Debian; 5 repetições cada, com e sem cache) | QP1 | Script no PC que usa a API (`/deploy_worker` → espera `RUNNING` → remove) | 3 h + execução |
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

## Ordem sugerida (atualizada em 16/11)

Fases 1, 1B e 2 concluídas (16/11), com duas rodadas de revisão. Daqui para frente:

```
Dia 1   scripts 3.1, 3.3, 3.4 → iniciar E7 (24 h)    ← dados rodando de noite
Dia 2   3.2, 3.5, 3.1 executado → git push            ← dados completos
Dia 3   4.1, 4.2, 4.6                                 ← resultados
Dia 4   4.3, 4.4, 4.5                                 ← texto fechado
Dia 5   4.7 + folga para imprevistos → orientador
```

Se o prazo for mais curto, corte nesta ordem: 1.6 → 3.5 → 3.2. **Não corte** 3.4, 3.1 nem 4.2: sem eles não há resultado.

## Riscos

| Risco | Mitigação |
|---|---|
| HyperOS ou Android 16 mata o Termux em segundo plano | Fazer 1.4 cedo; se não houver solução, deixar o celular na tela do Termux durante a demo e registrar como resultado (é um achado relevante para a QP3) |
| A rede da faculdade isola os dispositivos no Wi-Fi | Levar um roteador próprio ou usar o roteador do celular do Host (*hotspot*) na defesa |
| Sem internet no local da defesa | 2.5 (painel com arquivos locais); o `apk`/`apt` também precisa de internet: deixar os Workers da demo com os pacotes já instalados |
| O IP do celular ou do PC muda na hora (DHCP) | O painel acompanha o celular sozinho; se o PC mudar, "Adicionar" o Node de novo. Ensaiar uma vez antes |
| Um único aparelho | Assumir explicitamente como limitação ("prova de conceito com 1 nó") |
