# Próximos passos

Único documento com o que **falta** fazer no DroidServer (atualizado em 24/11/2026). O que já foi feito está em [`HISTORICO.md`](HISTORICO.md). Ao concluir um item, apague-o daqui e, se valer o registro, acrescente uma linha no histórico.

Prioridade: **(1) entregar o TCC, (2) a defesa, (3) o resto.**

## 1. Artigo — submissão

O parecer do orientador de 24/11 foi aplicado no vault (ver o histórico). Falta o que depende do autor ou do orientador:

- [ ] **Autoria (item 2 do parecer):** o orientador entra como coautor, com as contribuições CRediT na nota 09 (definido em 24/11). Nota de rodapé com cargo e e-mail preenchida (`META.autores` em `docs/gerador-docx/gerar.mjs`). Falta ele confirmar a coautoria, os papéis CRediT e se tem titulação acadêmica a acrescentar. O ORCID não é exigido pela Tópicos.
- [ ] **Tópicos:** mandar a declaração de uso de IA por e-mail após a submissão (política da revista, seção 15.2) e perguntar se a avaliação duplo-cego pede uma versão sem identificação dos autores.
- [ ] (Opcional) Conferir no original o número de Belkhir e Elmeligi (2018) — 85% a 95% da pegada anual de um smartphone vem da fabricação — e, se confirmado, voltar a citá-lo na seção 1.4. Por ora o texto só diz que a maior parte vem da fabricação.
- [ ] Gerar o PDF **pelo Word** e conferir todas as figuras (no LibreOffice elas já saíram cortadas).
- [ ] Mandar a versão final ao orientador antes do envio.
- [ ] Conferir as referências com a biblioteca se houver acesso ao texto oficial da NBR 6023 de 2025 (as mudanças vistas em fontes secundárias não atingem os tipos usados).
- [ ] Versionar o PDF final e fechar as issues #1 a #7 citando o *commit* de cada correção.
- [ ] Gerar os `.docx` (base do TCC e Tópicos, sempre juntos): `cd docs/gerador-docx && npm install && npm run gerar`. Edite sempre o vault (`docs/obsidian-valt/`), nunca os `.docx`.

## 2. Defesa

- [ ] Ensaiar a demonstração inteira uma vez: criar um Worker, abrir o serviço no navegador, terminal, gráfico.
- [ ] Subir o Host com `DROID_PANEL_PASSWORD` definida.
- [ ] Deixar os Workers da demonstração com os pacotes já instalados (o `apk`/`apt` precisa de internet).
- [ ] Levar um roteador próprio ou usar um *hotspot*, caso a rede da faculdade isole os dispositivos.
- [ ] Ligar o Host num *nobreak* ou usar um notebook com bateria.
- [ ] Se o IP do PC mudar na hora, "Adicionar" o Node de novo pelo painel (o do celular é acompanhado sozinho).

## 3. Experimento opcional

- [ ] **E7 com o Android em configuração padrão** (otimização de bateria ativa, sem *wake-lock*), mais 24 h no moto e40, para saber se a condição (c) da H1 é necessária e não só suficiente. Mesmo procedimento da E7 (`bench/README.md`).

## 4. Código

- [ ] **Tarefa entregue no máximo uma vez:** o Host esvazia a fila ao responder o sync; se a resposta se perder, a tarefa some (`desktop/app/routes.py`, `node_sync`). Confirmar a entrega no sync seguinte.
- [ ] **Atualização em dobro no Dashboard:** `fetch` a cada 5 s **e** a cada `node_updated` (`desktop/app/templates/index.html`, ~linha 742). Manter só um dos mecanismos.
- [ ] Constantes duplicadas à mão (`IMAGENS_PERMITIDAS`, `ALIAS_RE`) em `node.py`, `servico.py`, `routes.py` e `index.html`.
- [ ] Dependências do agente sem versão fixa no `pip install` do `setup.sh` (o `pyproject.toml`/`uv.lock` do `android/` só vale para os testes).
- [ ] `setup.sh` roda `pkg upgrade` completo a cada execução; separar "instalar" de "reconfigurar".
- [ ] `index.html` com ~1770 linhas (HTML, CSS e JS de todas as telas num arquivo).
- [ ] `SystemMonitor._prev_ts` gravado e nunca lido (`android/sysinfo.py`).
- [ ] **Workers de banco, próximos passos:** backup e restauração automáticos pelo painel (por ora, só os comandos `pg_dump`/`pg_restore` documentados no card Conexão); outros bancos (Redis, MariaDB) no mesmo molde do `android/banco.py`; mostrar a URL de conexão para Workers da mesma rede usarem como `DATABASE_URL`.

## 5. Organização do repositório

- [ ] `android/README.md` e `desktop/README.md` vazios (referenciados pelos `pyproject.toml`); `description = "Add your description here"` nos dois.
- [ ] `desktop/.python-version` versionado, apesar de o `.gitignore` ignorar `.python-version`.
- [ ] CI: GitHub Actions rodando o `pytest` do `desktop/` e do `android/`.
- [ ] **Depois da defesa — nomenclatura:** trocar no painel "Node" por **Dispositivo** (também acaba com a confusão com "Node.js" nos exemplos do `run.sh`) e "Worker" por **Instância** ("Sistema" foi descartado: lê-se como sistema operacional ou como o próprio DroidServer). Começar só pelos rótulos do `index.html` e do README; renomear código e protocolo (`/api/node_sync`, `criar_worker`, `node_updated`, `nodes.json`, `DROID_NODE_PORT`, ~1.200 ocorrências de "node" e ~450 de "worker") exigiria compatibilidade com os agentes já pareados e não traz ganho funcional.
- [ ] Depois da entrega: renomear `docs/obsidian-valt` para `docs/vault` (atualizar o gerador do `.docx`, os READMEs e reabrir o vault no Obsidian).

## Trabalhos futuros

Escalonador automático, persistência e reconciliação de estado no Host, *proxy* reverso com TLS, assistente que gera o `run.sh`, integração com repositório Git (CI/CD) e variáveis de ambiente, imagens prontas de Worker, testes com mais Nodes, comparação com Raspberry Pi e cálculo de carbono (CCI) estão resumidos na conclusão do artigo ([`obsidian-valt/08-conclusao.md`](obsidian-valt/08-conclusao.md)). Ficam fora do escopo da entrega.
