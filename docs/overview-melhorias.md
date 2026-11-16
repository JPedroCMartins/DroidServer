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
| 2.6 | **Debugger do Werkzeug exposto na rede** (`debug=True` + `host='0.0.0.0'`). Na prática, é execução remota de código para quem estiver na mesma rede. | `desktop/main.py` | Crítico se a rede não for 100% confiável |
| 2.7 | **Terminais difundidos para todos:** `socketio.emit(evento)` sem `to=`/`room=` manda a saída de todos os terminais para todos os navegadores e Nodes conectados, e qualquer cliente pode emitir `terminal_output` falso. | `routes.py:203-242` | Vazamento de dados entre sessões |
| 2.8 | **Delete via `GET`** — pré-carregamento do navegador, *crawlers* ou um `<img src>` malicioso podem apagar Workers (CSRF). | `routes.py:81` | Perda de dados |
| 2.9 | **Node identificado pelo IP.** DHCP muda o IP → Node duplicado no painel e Workers "órfãos"; dois Nodes atrás do mesmo NAT colidem; o IP também entra no nome de eventos. | `node.py`, `routes.py` | Confusão no painel |
| 2.10 | `SECRET_KEY` fixo no código e `cors_allowed_origins="*"`. | `desktop/app/__init__.py` | Má prática |
| 2.11 | ✅ **Corrigido.** `proot-distro remove` em `deletar` sem `timeout`; pode travar a fila de tarefas inteira. | `node.py:332` | Node "preso" processando |
| 2.12 | O conteúdo do `.conf` do Supervisor é gerado com indentação herdada da f-string. Funciona com o `configparser` atual, mas é frágil. | `node.py:214-221` | Usar `textwrap.dedent` |
| 2.13 | O PTY só abre na primeira tecla e o handler faz `time.sleep(0.5)` dentro do callback do Socket.IO; o usuário vê um terminal vazio até digitar. | `node.py:378-382` | UX ruim; abrir a sessão num evento `terminal_open` |

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
