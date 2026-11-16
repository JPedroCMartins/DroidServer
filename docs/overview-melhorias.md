# Overview: o que está desconexo, improdutivo ou deveria melhorar

Revisão feita em 15/11/2026 sobre todo o repositório (código, scripts, testes, `docs/obsidian-valt/` e `docs/artigo_nao_finalizado.odt`). Itens em ordem de impacto.

## 1. TCC × código: o que não conversa

| # | Problema | Onde | Sugestão |
|---|---|---|---|
| 1.1 | **Não há experimentos.** A metodologia diz "pesquisa experimental" e o objetivo diz "validar", mas não existe nenhum dado medido, script de benchmark ou capítulo de resultados. É a maior lacuna do trabalho. | metodologia, objetivos | Executar o protocolo da nota `09-avaliacao-experimental.md` |
| 1.2 | **Promessa de "acesso seguro"** ao terminal (objetivo específico) contradiz o código: o painel não tem login, roda `debug=True` em `0.0.0.0` e repassa terminais para qualquer cliente conectado. | `03-objetivos`, `desktop/` | Implementar autenticação mínima ou retirar "seguro" do objetivo e assumir como limitação |
| 1.3 | **"Isolamento" e "emulação"** são usados como se o PRoot fosse um contêiner. Em ARM sobre ARM o PRoot não emula nada e não isola rede, processos, CPU nem memória. Uma banca de engenharia vai questionar isso. | caps. 1, 2, 3, 5 | Já corrigido no vault (5.4 e 5.5); manter a terminologia "execução em espaço de usuário" |
| 1.4 | **Escalabilidade** está na questão de pesquisa, mas não há escalonador, nem teste com N nós, nem estado persistente. | `02-problema` | Removido "escalável" da questão; tratar como trabalho futuro ou medir com 3+ aparelhos |
| 1.5 | **Três títulos diferentes** (capa do .odt, folha de rosto do .odt e vault). | `docs/` | Escolher um só |
| 1.6 | **Duas fontes da verdade:** o `.odt` e o vault têm o mesmo texto, que vai divergir. | `docs/` | Escrever só no vault e gerar o .odt/.docx no final (Pandoc + modelo ABNT), ou abandonar o vault |
| 1.7 | **Terminologia trocada:** o texto chamava os celulares de "Workers", mas no código Worker é o container e o celular é o Node. | objetivos, problema, diagrama | Corrigido; tabela de convenção no README do vault |
| 1.8 | **Detalhes técnicos desatualizados:** `node_agent.py` (é `node.py`), `urllib` (não é usado), "SSH reverso" (não há SSH), Bootstrap (agora é Tailwind). | metodologia, README | Corrigido |
| 1.9 | **Citações inconsistentes:** Tanenbaum citado como 2013 e listado como 2007; Silberschatz citado como 2013 e listado como 2015; Coulouris, Shi, Fornwall e RFCx listados mas nunca citados (a ABNT não permite isso). | `05`, `08-referencias` | Corrigido; lista ampliada de 9 para ~45 referências |
| 1.10 | **Faltavam** trabalhos relacionados, hipótese, resumo/abstract, limitações/ameaças à validade e glossário. | vault | Notas novas criadas |
| 1.11 | Pasta chamada `obsidian-valt` (o certo seria *vault*). | `docs/` | Renomear (`git mv`) quando for commitar |

## 2. Bugs e riscos no código

| # | Problema | Onde | Impacto |
|---|---|---|---|
| 2.1 | ✅ **Corrigido.** **10 de 69 testes falham.** Os testes não acompanharam a migração para SPA (rotas `/node/...` agora sempre retornam 200; delete responde JSON em vez de 302), nem a inclusão de `isolado` e `ulimit`. Os commits recentes foram feitos sem rodar a suíte. | `desktop/tests`, `android/tests` | Os testes deixam de proteger o código |
| 2.2 | ✅ **Corrigido.** **Resultados de tarefa podem se perder.** `_poll_once` copia `_resultados`, faz o POST (até 5 s) e depois chama `_resultados.clear()`. Um resultado registrado pela thread de tarefas durante o POST é apagado sem nunca ser enviado. | `android/node.py:519-535` | O painel não mostra "✓ criado" de algumas operações |
| 2.3 | **Tarefas entregues no máximo uma vez.** O Host esvazia a fila ao responder o sync; se a resposta se perder (timeout depois de o Host processar), a tarefa some. | `desktop/app/routes.py:189-190` | Criação/remoção "esquecida" |
| 2.4 | ✅ **Corrigido.** **`supervisorctl` sem `-c`** em `criar` e `deletar`, mas com `-c` em `get_workers_status`. No modo HTTP com senha (Python sem `os.link()`), se o `supervisorctl` não achar o conf certo, o `reread/update` falha em silêncio (`check=False`) e o Worker não vira serviço. | `node.py:229-234, 258-259, 319-328` | Worker criado mas "sem serviço" |
| 2.5 | ✅ **Corrigido.** **Vazamento de PTY:** `encerrar()` e `_ler_saida()` nunca chamam `os.close(fd)` nem `os.waitpid(pid)`. Cada sessão encerrada deixa um descritor aberto e um processo zumbi. | `node.py:389-439` | Em sessões longas, esgota descritores e polui a tabela de processos |
| 2.6 | ✅ **Corrigido.** **Debugger do Werkzeug exposto na rede** (`debug=True` + `host='0.0.0.0'`). Na prática, é execução remota de código para quem estiver na mesma rede. | `desktop/main.py` | Crítico se a rede não for 100% confiável |
| 2.7 | **Terminais difundidos para todos:** `socketio.emit(evento)` sem `to=`/`room=` manda a saída de todos os terminais para todos os navegadores e Nodes conectados, e qualquer cliente pode emitir `terminal_output` falso. | `routes.py:203-242` | Vazamento de dados entre sessões |
| 2.8 | **Delete via `GET`** — pré-carregamento do navegador, *crawlers* ou um `<img src>` malicioso podem apagar Workers (CSRF). | `routes.py:81` | Perda de dados |
| 2.9 | ✅ **Corrigido.** Agora o painel cadastra os Nodes (varredura + pareamento) e cada um é identificado por um token exclusivo; uma troca de IP move o cadastro para o novo endereço. Problema original: **Node identificado pelo IP.** DHCP muda o IP → Node duplicado no painel e Workers "órfãos"; dois Nodes atrás do mesmo NAT colidem; o IP também entra no nome de eventos. | `node.py`, `routes.py` | Confusão no painel |
| 2.10 | 🟡 **Parcial:** a `SECRET_KEY` agora vem de `DROID_SECRET_KEY` ou é aleatória; o CORS `*` continua. `SECRET_KEY` fixo no código e `cors_allowed_origins="*"`. | `desktop/app/__init__.py` | Má prática |
| 2.15 | ✅ **Corrigido.** **CPU falsa de 0% no Android 16:** o `/proc/stat` é bloqueado pelo SELinux e o `top` do toybox também não enxerga a CPU (mostra `800%idle` e tudo zerado). O agente reportava 0,0% como se fosse medição. Agora devolve `None` e o painel mostra "—". | `android/sysinfo.py` | O painel e os dados do TCC mostrariam a CPU sempre ociosa |
| 2.16 | ✅ **Corrigido (confirmado no aparelho).** **Remover um Worker falhava:** o `proot-distro remove` exige o lock exclusivo do container e falha na hora se uma sessão `login` (o serviço do Supervisor ou o terminal) ainda está terminando — o que sempre acontecia logo após parar o serviço. Agora o agente encerra as sessões com `proot-distro kill`, tenta o remove até 5 vezes e relata a mensagem real de erro. | `android/node.py` (`_remover_container`) | O container ficava no disco e o painel mostrava ✗ |
| 2.18 | ✅ **Corrigido.** **Resultados sumiam do painel em ~10 s:** o agente envia cada ✓/✗ uma única vez, mas o Host substituía a lista a cada sync, então o resultado sumia no sync seguinte (a falha do Arch passou despercebida por isso). O Host agora acumula os últimos 20, sem duplicar reenvios. | `desktop/app/routes.py` | Falhas de criação/remoção podiam passar despercebidas |
| 2.19 | ✅ **Corrigido.** **Serviço registrado antes do script existir:** o Worker era registrado no Supervisor antes de o `/app/run_server.sh` ser criado; funcionava por sorte (injeção rápida). Agora o script é criado antes do registro. | `android/node.py` | Worker podia terminar em `FATAL` logo após a criação |
| 2.17 | ✅ **Corrigido.** **Status dos Workers sumia quando um falhava:** o `supervisorctl status` sai com código 3 sempre que algum programa não está `RUNNING`, e o agente descartava a saída inteira nesse caso — bastava um Worker `FATAL` para todos aparecerem como "sem serviço". Agora a saída é lida independentemente do código de retorno. | `android/node.py` | Painel mostrava estado errado justamente quando havia falha |
| 2.20 | ✅ **Corrigido.** **O serviço do Worker não era controlável pelo painel:** o arquivo a editar (`/app/run_server.sh`) era uma convenção escondida, trocá-lo não fazia nada sem reiniciar pelo SSH, não havia botões nem logs no painel e um serviço com `&` caía em `FATAL` sem explicação. Agora: lançador que espera o `/app/run.sh`, aba Serviço com editor, Iniciar/Parar/Reiniciar, opções de quando rodar e logs ao vivo. | `android/servico.py`, painel | Usuário não conseguia operar o próprio serviço |
| 2.21 | ✅ **Corrigido.** **Processos antigos seguravam a porta ao reiniciar:** sem `stopasgroup/killasgroup`, o programa do usuário sobrevivia ao `proot-distro` e o serviço novo ficava `FATAL` por *"Address in use"* (visto na migração). | `android/servico.py` | Serviços que não voltavam após reinício |
| 2.22 | ✅ **Corrigido (confirmado no aparelho).** **O agente não percebia a troca de IP:** o IP era detectado uma vez, ao iniciar. Depois de o Wi-Fi ser religado (DHCP: .7 → .5), o agente seguia informando o IP antigo, e a migração por token do Host (2.9) nunca era acionada: o painel mostrava o Node no IP velho, e "Remover" despareava o endereço errado. Agora o IP é detectado de novo a cada ciclo. | `node.py` (`_atualizar_ip`) | Node "preso" no IP antigo |
| 2.23 | ✅ **Corrigido.** **Criar ou apagar um Worker reiniciava outros:** `criar`, `deletar` e a migração usavam `supervisorctl update` sem nome, que aplica **todos** os `.conf` pendentes. Um Worker com autostart alterado (que só vale no próximo reinício) era reiniciado sem aviso quando outro Worker era criado. Agora é `update <alias>`. | `node.py`, `servico.py` | Reinício inesperado de serviços |
| 2.24 | ✅ **Corrigido (confirmado no aparelho).** **Logs paravam depois de o agente reiniciar:** o agente esquecia as assinaturas, mas o navegador continuava na sala e não recebia mais nada. Agora o sync informa `logs_ativos` e o Host reenvia `assinar`/`cancelar` até alinhar. | `routes.py` (`_reconciliar_logs`) | Aba Serviço "congelada" |
| 2.25 | ✅ **Corrigido (confirmado no aparelho).** **O exemplo do `run.sh` não rodava no Alpine:** usava `python3`, que o Alpine (distribuição recomendada) não traz. O exemplo agora instala o Python na primeira execução (`apk` ou `apt`). | `servico.py` (`EXEMPLO`) | Primeiro uso frustrado |
| 2.26 | **Painel depende de internet:** Tailwind, xterm.js, Socket.IO e fontes vêm de CDNs. Sem internet (rede de laboratório, apresentação), o painel não carrega (`io is not defined`). Sugestão: servir cópias locais em `static/`. | `index.html` | Painel inutilizável offline |
| 2.27 | ✅ **Corrigido.** **PC do painel com IP novo não conseguia readicionar o Node:** o node só aceita pareamento do host salvo e respondia 409 ao mesmo PC com IP novo, sem saída pelo painel (só apagando o `pareamento.json` por SSH). Agora o Host manda o token atual (`token_atual`) e o node aceita quem o prova. | `node.py` (`Descoberta.parear`), `routes.py` | Node inalcançável |
| 2.28 | ✅ **Corrigido (confirmado no aparelho).** **O lançador ignorava o *shebang*:** sempre rodava `sh /app/run.sh`, então `#!/bin/bash` ou `#!/usr/bin/env python3` quebravam (no Alpine o `sh` é o BusyBox). Agora um `run.sh` executável com `#!` roda com o interpretador indicado. Os lançadores antigos são atualizados ao iniciar o agente, sem reiniciar serviços. | `servico.py` (`LANCADOR`) | Scripts válidos falhando |
| 2.29 | ✅ **Corrigido (confirmado no aparelho).** **Link simbólico furava o isolamento:** o agente lê/grava o `run.sh` pelo Termux, fora do proot; um link `/app/run.sh → ~/.config/droidserver/pareamento.json` criado dentro do container fazia a aba Serviço mostrar o token (ou sobrescrever o arquivo). Agora links no caminho são recusados. | `servico.py` (`_dentro_do_container`) | Vazamento do token / escrita fora do container |
| 2.30 | ✅ **Corrigido.** **Opções da aba Serviço apagavam os limites:** `configurar` e a migração regravavam o `.conf` com os `ulimit` padrão, ignorando `DROID_ULIMIT_NOFILE/NPROC`. | `servico.py` | Limites perdidos |
| 2.31 | ✅ **Corrigido.** **Falha no `exec` do terminal deixava um agente duplicado:** se o `proot-distro` não pudesse ser executado no filho do `pty.fork()`, a exceção continuava rodando uma cópia do agente. Agora o filho sai com `os._exit(127)`. Também o `desparear` passou a comparar o token em tempo constante (`hmac`). | `node.py` (`iniciar_pty`) | Processos duplicados |
| 2.14 | ✅ **Corrigido.** **O Host não subia sem terminal interativo:** o Flask-SocketIO recusa o Werkzeug sem TTY, então não dava para rodar o Host como serviço (systemd, `nohup`). Agora usa `allow_unsafe_werkzeug=True`, com debug desligado por padrão e permitido só em localhost (`DROID_BIND`/`DROID_PORT`/`DROID_DEBUG`). | `desktop/main.py`, `desktop/app/__init__.py` | Encontrado ao testar com um aparelho real |
| 2.11 | ✅ **Corrigido.** `proot-distro remove` em `deletar` sem `timeout`; pode travar a fila de tarefas inteira. | `node.py:332` | Node "preso" processando |
| 2.12 | O conteúdo do `.conf` do Supervisor é gerado com indentação herdada da f-string. Funciona com o `configparser` atual, mas é frágil. | `node.py:214-221` | Usar `textwrap.dedent` |
| 2.13 | ✅ **Corrigido (confirmado no aparelho).** O PTY só abre na primeira tecla e o handler faz `time.sleep(0.5)` dentro do callback do Socket.IO; o usuário vê um terminal vazio até digitar. | `node.py:378-382` | UX ruim; abrir a sessão num evento `terminal_open` |

### Validação em aparelho real (15/11/2026)

Xiaomi 2311DRK48G, Android 16, aarch64, 8 núcleos, 7,5 GB de RAM, Termux + `proot-distro` com o layout `containers/`:

- `setup.sh` concluído sem intervenção; suíte do agente **52/52** no próprio celular;
- Node registrado no Host; Worker Alpine criado pelo painel em ~10 s (rootfs já em cache) e em `RUNNING` no Supervisor;
- terminal: `--isolated` confirmado (`/sdcard` não existe dentro do Worker); após `exit`, o descritor do PTY é fechado e não restam processos-filho nem zumbis (correção 2.5 confirmada);
- remoção pelo painel com o terminal aberto: container, `.conf`, logs e sessão removidos, sem zumbis (correção 2.16; antes falhava com `exit status 1`);
- reboot do celular: o Termux:Boot subiu o agente sozinho e os 4 Workers voltaram `RUNNING`, com as aplicações respondendo; **o IP mudou de .7 para .4** (DHCP), o que confirma o problema 2.9;
- Debian criado pelo painel em ~80 s (com `apt`); Arch indisponível (imagem oficial sem `arm64`) e retirado do painel;
- cadastro pelo painel: varredura de 192.168.1.0/24 em 3,2 s encontrou o celular (modelo e Android); "Adicionar" o deixou *Online* com os 4 Workers; remover/readicionar e reiniciar o Host funcionaram; pareamento vindo de outro endereço foi recusado. O IP do celular mudou de novo (.4 → .7) durante os testes;
- **CPU sem *root*:** testadas duas fontes acessíveis. O tempo ocioso em `/sys/.../cpuidle` **não é confiável** (marca ~40% em repouso e não cresce com a carga). A soma de `utime+stime` dos processos do Termux em `/proc/<pid>/stat` acompanhou a carga gerada (22,9 / 49,8 / 87,5% para 25 / 50 / 100%) e foi implementada como **CPU do DroidServer** (total e por Worker). Validação no painel: 2 loops dentro de um Worker → 25,0% no total e 24,9% atribuídos ao Worker.

## 3. Improdutivo ou redundante

- **Atualização em dobro no painel:** o Dashboard faz `fetch` a cada 5 s **e** a cada `node_updated` — que o Host emite a cada sync de cada Node. Com 3 Nodes, são cerca de 50 requisições por minuto por aba aberta. Basta enviar o estado no próprio evento, ou manter só um dos mecanismos.
- **Constantes duplicadas** (`IMAGENS_PERMITIDAS`, `ALIAS_RE`) no Host, no agente e no JS, mantidas "à mão" — o comentário já admite isso.
- **Dependências do Node em dois lugares:** `android/pyproject.toml` + `uv.lock` (usados só nos testes) e o `pip install` fixo no `setup.sh` (usado no celular), sem versões fixadas. Uma atualização do `python-socketio` pode quebrar o Node sem ninguém perceber.
- **`setup.sh` roda `pkg upgrade` completo** em toda execução, mesmo quando só se quer trocar o IP do Host — lento e arriscado. Separe "instalar" de "reconfigurar".
- **Tailwind via Play CDN** compila CSS no navegador a cada carregamento e exige internet; o próprio Tailwind desaconselha isso em produção. Num cluster de LAN sem internet, o painel fica sem estilo e o terminal sem xterm.js.
- `index.html` com 837 linhas (HTML + CSS + JS das três telas) num único arquivo.
- `SystemMonitor._prev_ts` é gravado e nunca usado.

## 4. Organização do repositório

- `android/README.md` e `desktop/README.md` estão vazios, mas são referenciados no `pyproject.toml`; as descrições ainda dizem "Add your description here" e os pacotes se chamam `android` e `droidserver`.
- `.gitignore` ignora `.python-version`, mas `desktop/.python-version` está versionado.
- Não há CI: um GitHub Actions rodando os dois `pytest` teria impedido que os testes ficassem desatualizados (item 2.1).
- Não há licença (`LICENSE`); para um artigo e um repositório público, defina uma (MIT ou GPL).
- Mensagens de commit misturam `feat:` em correções e textos genéricos ("artigo em docs").
- O `.odt` binário versionado não permite revisar diferenças pelo Git.

## 5. Prioridades sugeridas para o TCC

1. **Rodar os experimentos** (nota 09): sem resultados, o trabalho é um relato de desenvolvimento, não uma pesquisa experimental.
2. ~~Consertar os testes (2.1) e corrigir 2.2, 2.4 e 2.5~~ — feito: 78 testes passando, com regressões para cada bug.
3. **Endurecimento mínimo de segurança** (2.6–2.8: `debug=False`, rooms por sessão, delete via `POST`, login simples), ou declarar explicitamente como limitação e tirar "seguro" dos objetivos.
4. **ID estável por Node** (UUID salvo no `env`) em vez do IP.
5. **Unificar o título** e escolher uma única fonte do texto (vault **ou** .odt).
6. Conferir as referências marcadas com ⚠ e ler na íntegra os artigos de Switzer et al. (2023), Shahrad e Wentzlaff (2017) e Büsching et al. (2012) — são os mais próximos do seu trabalho e a banca vai esperar a comparação.
