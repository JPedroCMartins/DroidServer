# Aba Serviço mais amigável — proposta (aguardando decisões)

Data: 16/11/2026 · Situação: **abordagem B escolhida pelo usuário (16/11)**; demais decisões na seção 6 (propostas, aguardando aprovação).

## 1. Intenção

Quem abre a aba Serviço de um Worker precisa entender, sem ler o README nem abrir o terminal: **o que roda, se está funcionando, onde acessar e o que fazer quando não funciona**. Hoje a aba só faz sentido para quem já sabe escrever um *shell script* de serviço em primeiro plano. O objetivo é que um colega de laboratório (ou a banca, na demonstração) consiga colocar uma aplicação no ar pelo painel.

**Metas**
- Ajuda visível ("?") explicando o `/app/run.sh`: regras, passo a passo, exemplos por tipo de aplicação, erros comuns e o significado de cada estado.
- Mais informação na tela: endereço de acesso, reinícios e último erro, recursos (CPU, RAM, disco), distribuição e datas.
- Um caminho para criar o serviço **sem escrever shell** (assistente), mantendo o `run.sh` como fonte única da verdade.

**Fora do escopo agora**: vários serviços por Worker, agendamento (cron), *proxy* reverso, TLS.

**Antimetas** (seria um fracasso mesmo funcionando): esconder o `run.sh` de quem sabe usar; criar um segundo formato de configuração que diverge do arquivo; travar a tela com consultas pesadas no aparelho (o `du` do Worker, por exemplo).

## 2. Como é hoje

```
┌ ● Rodando · pid 8709 · no ar há 5:52:56     [Iniciar] [Parar] [Reiniciar] ┐
│ ☑ Iniciar junto com o celular   ☑ Reiniciar automaticamente se cair       │
├ /app/run.sh                [Inserir exemplo] [Salvar] [Salvar e reiniciar] ┤
│ (editor de texto simples)                                                 │
├ Logs ao vivo                           [Pausar] [Limpar] [Baixar]         ┤
└───────────────────────────────────────────────────────────────────────────┘
```

- Sem endereço de acesso, sem histórico de reinícios, sem recursos do serviço.
- Ajuda = comentários do "Inserir exemplo" + avisos de `&`/`nohup`.
- "Iniciar" fica habilitado com o serviço rodando.
- Colocar o código da aplicação em `/app` só é possível pelo terminal (`git clone`, `cat > arquivo`).

**Restrições verificadas no aparelho (Android 16, sem *root*)**
- `/proc/net/tcp` e `/proc/net/tcp6` → *Permission denied*: **não dá para descobrir sozinho em que porta o serviço escuta**. A porta precisa ser informada pelo usuário; o Host pode então testar `http://<ip>:<porta>/` a partir do PC.
- RSS do processo do Supervisor é só o *wrapper* do proot (~3 MB): a RAM real exige somar a árvore de processos (o agente já percorre essa árvore para a CPU por Worker).

## 3. Abordagens consideradas

| | Abordagem | Como fica para o usuário | Custo | Trade-off |
|---|---|---|---|---|
| **A** | **Só ajuda + informações** | "?" com guia e exemplos; painel de informações; o usuário continua escrevendo o `run.sh` | Baixo (só painel + pequenos dados do agente) | Continua exigindo shell |
| **B** ⭐ | **Assistente que gera o `run.sh`** (+ A) | "Configurar serviço": escolhe o tipo (site estático, API Python, Node.js, bot/script, comando livre), preenche porta, pasta, pacotes e comando; o painel **gera o `run.sh`** e mostra o resultado no editor | Médio (painel; agente só guarda metadados) | O arquivo continua sendo a verdade; quem sabe shell edita direto ("modo avançado") |
| **C** | **Serviço estruturado, sem shell** (estilo Procfile/Heroku) | Formulário vira a configuração (JSON); o agente monta o processo | Alto (modelo de dados novo, migração, agente) | Mais "produto", mas cria um segundo formato e perde a flexibilidade do shell |

**Recomendação: B (que inclui A).** Dá o caminho sem shell para quem precisa e não tira nada de quem já usa o `run.sh`. A porta informada no assistente resolve a restrição de rede (seção 2). C seria o caminho de um produto comercial, mas não cabe no prazo nem acrescenta ao TCC.

## 4. Proposta de tela (B)

```
Worker demo_api · Alpine 3.24                              [Serviço] [Terminal]
┌ Visão geral ─────────────────────────────────────────────────────────────┐
│ ● Rodando há 5h52      pid 8709      [Parar] [Reiniciar]   (Iniciar só   │
│                                                            quando parado)│
│ Endereço  http://192.168.1.5:8080  [Abrir] [Testar ✓ 200 em 38 ms]     │
│ Reinícios hoje: 0 · Última falha: — · Iniciar com o celular ☑ (?)        │
│ CPU 0,4% · RAM 21 MB · Disco 55 MB · run.sh salvo há 2 h                 │
├ /app/run.sh  (?) ──────────────── [Assistente] [Salvar] [Salvar e reiniciar]┤
│  1 │ #!/bin/sh                                                           │
│  2 │ # droidserver: porta=8080                                           │
│  3 │ cd /app && exec python3 app.py                                      │
├ Logs ao vivo ─────────────────── [Pausar] [Limpar] [Baixar] ─────────────┤
└──────────────────────────────────────────────────────────────────────────┘

(?) abre um painel lateral "Como colocar sua aplicação no ar":
  1. Coloque os arquivos em /app (Terminal: git clone ... /app)
  2. Instale o que ela precisa (apk add python3 / apt install ...)
  3. Escreva o run.sh: primeiro plano, `exec` no último comando, sem & nem nohup
  4. Informe a porta e use "Salvar e reiniciar"
  Exemplos: site estático · API Python · Node.js · bot · comando livre
  Erros comuns: "Falhou" logo ao iniciar, "Address in use", comando não encontrado
  O que significa cada estado: Rodando / Iniciando / Falhou / Parado / Aguardando run.sh
```

**Assistente** (modal, 2 passos): (1) tipo de aplicação → (2) campos do tipo (porta, pasta, pacotes a instalar na 1ª execução, comando) → mostra o `run.sh` gerado → "Usar este script". Os metadados ficam no próprio arquivo, em comentários (`# droidserver: porta=8080 tipo=api-python`), para não existir um segundo formato.

**Mudanças por parte**
- *Painel:* bloco "Visão geral", botão "?" com painel lateral de ajuda, assistente, editor com números de linha, botões habilitados conforme o estado.
- *Agente:* ler os metadados do cabeçalho do `run.sh` (porta, tipo); contar reinícios (linhas "[DroidServer] Iniciando" no log do dia); RAM da árvore de processos; disco do Worker calculado em segundo plano e guardado em cache (não a cada *sync*); data do último salvamento.
- *Host:* ação "Testar endereço" (GET a partir do PC, com tempo de resposta).

## 5. Riscos

- O `du` de um Worker Debian leva segundos: fazer em *thread*, no máximo a cada 10 min.
- A contagem de reinícios pelo log se perde na rotação (1 MB × 3): aceitar "desde a última rotação" ou guardar um contador no agente.
- Mudanças no agente só no POCO até a E7 terminar (17/11, ~14h).

## 6. Decisões

| # | Questão | Decisão | Origem |
|---|---|---|---|
| 1 | Abordagem | **B — assistente que gera o `run.sh`**, incluindo a ajuda "?" e a visão geral (A) | usuário |
| 2 | Código no `/app` sem terminal | **Campo "repositório Git"** no assistente: o `run.sh` gerado faz `git clone` (instala o git se faltar) na 1ª execução e não clona de novo se `/app` já tiver o repositório. Envio de arquivos pelo painel fica para trabalhos futuros | proposta |
| 3 | Variáveis de ambiente | **Campo próprio**: gravadas em `/app/.droidserver/env` (0600) e carregadas pelo lançador antes do `run.sh`; o painel lista só os **nomes** (valores não voltam ao navegador nem aparecem em logs); editar = substituir o valor | proposta |
| 4 | Tipos do assistente | Site estático · API Python · Node.js · bot/script Python · comando livre | proposta |
| 5 | Prioridade | S1 (ajuda "?") e S2 (visão geral) primeiro; depois S3, S4 (assistente), S5, S6 | proposta |

**Consequências no agente** (além da seção 4): o lançador passa a carregar `/app/.droidserver/env` se existir (mudança de versão do lançador; a atualização automática já existe); nova ação `variaveis` (listar nomes, definir, remover) no canal `servico`; o editor do `run.sh` não exibe o arquivo de variáveis.

**Fora desta fase:** envio de arquivos pelo painel, vários serviços por Worker, detecção automática de porta (bloqueada sem *root*).
