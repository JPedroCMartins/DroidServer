# Próximos passos

Único documento com o que **falta** fazer no DroidServer (atualizado em 18/11/2026). O que já foi feito está em [`HISTORICO.md`](HISTORICO.md). Ao concluir um item, apague-o daqui e, se valer o registro, acrescente uma linha no histórico.

Prioridade: **(1) entregar o TCC, (2) a defesa, (3) o resto.**

## 1. TCC — entrega

- [ ] Preencher as lacunas em amarelo do `.docx`: nome do(a) orientador(a), e-mail na nota de rodapé e o aviso de revisão do Quadro 2 (trabalhos relacionados).
- [ ] Aplicar o modelo oficial da Uninorte, se houver (capa, margens, fontes).
- [ ] Enxugar o texto (repetições entre os capítulos 8, 9 e 11).
- [ ] Conferir no artigo original o número de Belkhir e Elmeligi (2018): 85% a 95% da pegada anual de um smartphone vem da fabricação (a fonte consultada foi uma reportagem).
- [ ] (Opcional) Ler na íntegra Switzer et al. (2023) e Shahrad e Wentzlaff (2017), os trabalhos mais próximos, e reforçar a comparação no capítulo 6.
- [ ] Revisão do(a) orientador(a).
- [ ] Gerar o `.docx` final: `cd docs/gerador-docx && npm install && npm run gerar`. Edite sempre o vault (`docs/obsidian-valt/`), nunca o `.docx`.

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

## 5. Organização do repositório

- [ ] `android/README.md` e `desktop/README.md` vazios (referenciados pelos `pyproject.toml`); `description = "Add your description here"` nos dois.
- [ ] `desktop/.python-version` versionado, apesar de o `.gitignore` ignorar `.python-version`.
- [ ] CI: GitHub Actions rodando o `pytest` do `desktop/` e do `android/`.
- [ ] Definir uma licença (`LICENSE`).
- [ ] Depois da entrega: renomear `docs/obsidian-valt` para `docs/vault` (atualizar o gerador do `.docx`, os READMEs e reabrir o vault no Obsidian).

## Trabalhos futuros

Escalonador automático, persistência e reconciliação de estado no Host, *proxy* reverso com TLS, assistente que gera o `run.sh`, integração com repositório Git (CI/CD) e variáveis de ambiente, imagens prontas de Worker, testes com mais Nodes, comparação com Raspberry Pi e cálculo de carbono (CCI) estão descritos na seção 10.3 do TCC ([`obsidian-valt/10-limitacoes-e-trabalhos-futuros.md`](obsidian-valt/10-limitacoes-e-trabalhos-futuros.md)). Ficam fora do escopo da entrega.
