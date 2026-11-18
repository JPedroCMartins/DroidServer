# Histórico do projeto

O que já foi feito no DroidServer, em resumo. Os detalhes (decisões, telas propostas, discussão de cada bug) estão nos commits e nos PRs; os documentos de planejamento antigos (`docs/plano-proximos-passos.md`, `docs/overview-melhorias.md` e `docs/superpowers/`) foram removidos em 18/11/2026 e podem ser lidos pelo histórico do Git. O que falta fazer está em [`PROXIMOS-PASSOS.md`](PROXIMOS-PASSOS.md).

## Linha do tempo

| Data | Marco |
|---|---|
| 07/05/2026 | Primeiro protótipo: Host Flask, agente no Termux, Worker com `proot-distro` e Supervisor |
| 25/08/2026 | Painel web, monitoramento de CPU e memória, `setup.sh` de primeiro uso, terminal web, script de diagnóstico |
| 01–02/11 | Painel em SPA com Tailwind; Alpine, Debian (e Arch, retirado depois: sem imagem `arm64`); Worker `--isolated` (sem `/sdcard`) |
| 13/11 | Primeira versão do artigo em `docs/` |
| 15/11 | Revisão completa do repositório e do texto (overview de melhorias); correção dos testes e dos primeiros bugs; README reescrito; vault do TCC revisado |
| 15/11 | **Fase 1 — demonstração de ponta a ponta:** aplicação rodando num Worker e acessível na rede; Termux:Boot e reboot validados; cadastro de Nodes pelo painel (varredura + token); gráfico de CPU/RAM em tempo real; segundo Node (moto e40) |
| 16/11 | **Fase 1B — serviço do Worker pelo painel:** `/app/run.sh` como serviço, lançador, migração dos Workers antigos, Iniciar/Parar/Reiniciar, opções de inicialização e logs ao vivo |
| 16/11 | **Fase 2 — segurança mínima:** senha do painel (`DROID_PANEL_PASSWORD`), WebSocket do Node autenticado por token, terminal e logs por sala, remoção só via `POST`, bloqueio de `POST` de outros sites, CORS restrito, painel sem internet (`static/vendor/`) |
| 16/11 | **Fase 2B — aba Serviço amigável** (abordagem A): ajuda "?", visão geral (endereço, Testar, reinícios, CPU/RAM/disco), porta no cabeçalho `# droidserver: porta=8080`, editor com números de linha |
| 16/11 | **Fase 3 — experimentos:** E1/E2/E5 (provisionamento), E3 (sobrecarga do PRoot), E4 (latência do terminal), E8 (vazão), E10 (consumo do agente); registro local de métricas no Node (o painel pode ficar desligado) |
| 17/11 | **E7 — disponibilidade em 24 h** no moto e40 (16/11 23:21 a 17/11 23:21): **99,94%**, 0 reinícios do serviço, 4 lacunas curtas do agente (a maior de 25 s) |
| 16–17/11 | Apresentação do TCC em `/apresentar_tcc`, painel em Docker, visual do portfolio-page, copiar e colar no terminal por HTTP (PRs #24–#29) |
| 18/11 | **Cloudflare Tunnel** (fora do escopo do TCC): `cloudflared` no Termux como programa `tunnel` do Supervisor, token pelo painel (só os 4 últimos caracteres voltam), instalação sob demanda e logs ao vivo; validado no moto e40 com token de teste |
| 18/11 | **Workers de banco: PostgreSQL** (fora do escopo do TCC): novo tipo de Worker, com o PostgreSQL nativo do Termux (o `initdb` trava dentro do proot por causa da emulação System V), senha gerada pelo Host e mostrada só sob pedido, card Conexão, teste TCP e `psql` no Terminal; validado no moto e40 |
| 18/11 | **Workers de banco, refinamento:** vários bancos por instância (usuário dono por banco, criar/apagar pelo painel), pacote preso com `apt-mark hold` e aviso de versão incompatível (major dos dados ≠ binário), comandos de migração (`pg_dump`/`pg_restore`/`pg_dumpall`) no card Conexão |
| 16–18/11 | **Fase 4 — texto:** título único, resumo/abstract, conclusão, capturas do painel (8.8), gerador do `.docx` a partir do vault, resultados da E7 (PR #30), referências ⚠ conferidas na Crossref com DOIs (PR #31); orientador, e-mail e Quadro 2 conferidos nas fontes (Junkyard: Ubuntu Touch + Docker Swarm) |

## Bugs corrigidos (numeração da revisão de 15/11)

- **2.1** 10 de 69 testes falhavam depois da migração para SPA; suíte atualizada (hoje são 255 testes).
- **2.2** Resultados de tarefa apagados se chegassem durante o POST do sync.
- **2.4** `supervisorctl` sem `-c` em `criar`/`deletar`: Worker criado "sem serviço".
- **2.5** Vazamento de PTY (descritor aberto e processo zumbi por sessão).
- **2.6** Debugger do Werkzeug exposto na rede; debug só em `127.0.0.1`.
- **2.7** Saída de terminal difundida para todos os clientes; agora por sala e Node autenticado.
- **2.8** Remoção via `GET` (CSRF); agora só `POST` com verificação do `Origin`.
- **2.9** Node identificado pelo IP; agora por token, com migração automática de IP.
- **2.10** `SECRET_KEY` fixa e CORS `*`; chave persistente e CORS restrito.
- **2.11** `proot-distro remove` sem `timeout` podia travar a fila de tarefas.
- **2.12** `.conf` do Supervisor gerado com indentação herdada da f-string; agora montado linha a linha (`servico.conteudo_conf`).
- **2.13** Terminal vazio até a primeira tecla; sessão aberta ao conectar.
- **2.14** Host não subia sem terminal interativo (systemd, `nohup`).
- **2.15** CPU falsa de 0% no Android 16 (SELinux bloqueia `/proc/stat`); agora "—" e, depois, CPU do DroidServer pela soma dos processos do Termux.
- **2.16** Remoção de Worker falhava pelo lock do container; agora `proot-distro kill` + 5 tentativas.
- **2.17** Um Worker `FATAL` fazia todos aparecerem "sem serviço" (código 3 do `supervisorctl`).
- **2.18** Resultados ✓/✗ sumiam do painel no sync seguinte; Host acumula os últimos 20.
- **2.19** Serviço registrado antes de o script existir.
- **2.20** Serviço do Worker não controlável pelo painel; resolvido pela aba Serviço (Fase 1B).
- **2.21** Processos antigos seguravam a porta (`stopasgroup`/`killasgroup`).
- **2.22** Agente não percebia a troca de IP do celular; IP detectado a cada ciclo.
- **2.23** Criar/apagar um Worker reiniciava outros (`supervisorctl update` sem nome).
- **2.24** Logs paravam depois de o agente reiniciar; reconciliação de assinaturas no sync.
- **2.25** Exemplo do `run.sh` não rodava no Alpine (sem `python3`).
- **2.26** Painel dependia de CDNs; bibliotecas servidas pelo Host.
- **2.27** PC do painel com IP novo não conseguia readicionar o Node (`token_atual`).
- **2.28** Lançador ignorava o *shebang* do `run.sh`.
- **2.29** Link simbólico em `/app/run.sh` permitia ler/gravar fora do container (inclusive o token).
- **2.30** Opções da aba Serviço apagavam os limites `DROID_ULIMIT_*`.
- **2.31** Falha no `exec` do terminal deixava um agente duplicado; `desparear` com comparação em tempo constante.
- **2.32** Agente preso em *long-polling* (achado na E4); WebSocket direto: p95 de 321 → 58 ms em 5 GHz.
- **2.33** Migração de IP aceitava qualquer texto; só IPv4 de rede local.
- **2.34** Mensagem final do `setup.sh` citava o antigo `/app/run_server.sh`.

Também resolvidos na revisão do texto: título único; terminologia Host/Node/Worker; PRoot descrito como execução em espaço de usuário (não contêiner); detalhes técnicos desatualizados; citações e referências consistentes; notas novas (trabalhos relacionados, hipótese, resumo, limitações, glossário); uma só fonte do texto (vault → `.docx`).

## Validações em aparelho

- **15/11, POCO X6 Pro (Android 16):** `setup.sh` sem intervenção; suíte do agente no celular; Worker Alpine em ~10 s e Debian em ~80 s pelo painel; `--isolated` confirmado; remoção com terminal aberto sem zumbis; reboot com Termux:Boot e Workers de volta em `RUNNING`; varredura da rede em 3,2 s; troca de IP por DHCP absorvida; CPU sem *root* validada pela soma de `utime+stime` dos processos do Termux (o `cpuidle` não é confiável).
- **16/11, ambos os Nodes:** Fases 1B, 2 e 2B validadas de ponta a ponta (segundo navegador não recebe o terminal de outro; saída forjada descartada; login/logout; serviços com `run.sh` com falha, exemplo, Parar/Iniciar).
- **16/11, queda de energia:** o PC (Host) desligou; o moto e40 seguiu na bateria e o serviço não reiniciou.
- **17/11, moto e40:** E7 de 24 h com o painel desligado em parte do tempo.

## Decisões que continuam valendo

- O Host só gerencia: os Nodes seguem funcionando e gravando métricas com o painel desligado.
- Cada Node é identificado pelo token do pareamento, não pelo IP; IP fixo no roteador é desnecessário.
- O serviço de um Worker é sempre o `/app/run.sh`; a porta é declarada no cabeçalho (`# droidserver: porta=8080`), porque sem *root* o Android nega `/proc/net/tcp`.
- Reiniciar ao editar não é automático ("Salvar e reiniciar").
- Aba Serviço na abordagem A (ajuda + visão geral); o assistente que gera o `run.sh` (B), a configuração sem shell (C), repositório Git e variáveis de ambiente ficaram para trabalhos futuros (CI/CD, seção 10.3 do vault).
- Testes, deploys e experimentos só no moto e40; o POCO é o celular pessoal.
- PostgreSQL roda fora do proot (pacote do Termux): no proot, o `initdb` trava na emulação de memória compartilhada System V (`--sysvipc`).
- Versão do PostgreSQL não é escolhível (o Termux só empacota uma); o pacote fica preso (`apt-mark hold`) e a troca de major é manual, via dump/restore. Migração de dados fica nos comandos documentados, sem backup automático pelo painel.
- Os nomes Node e Worker ficam como estão até a defesa: aparecem no protocolo com os Nodes já pareados, nos testes, no bench e no texto e nas capturas do TCC.
