# **DroidServer: gerenciamento de ambientes Linux do tipo VPS em smartphones Android reaproveitados sem acesso root**

*EN: DroidServer: managing VPS-like Linux environments on repurposed Android smartphones without root access*

**CENTRO UNIVERSITÁRIO DO NORTE — UNINORTE**
**Engenharia da Computação — TCC**

**Aluno:** João Pedro Correia Martins (03339414)
**Turno:** Noturno
**Curso:** Engenharia da Computação — 7º Período

> Trabalho de Conclusão de Curso apresentado ao curso de Engenharia da Computação do Centro Universitário do Norte — Uninorte, como requisito parcial para obtenção do título de Bacharel em Engenharia da Computação.
>
> Esta documentação serve de base para a escrita de um artigo científico a ser submetido a periódico.

Manaus - AM, 2026

> [!tip] Versão em Word
> Estas notas geram duas versões do mesmo artigo (`cd docs/gerador-docx && npm install && npm run gerar`), sempre juntas, para não se desalinharem: `docs/DroidServer_TCC_artigo.docx`, o artigo base do TCC, com capa e folha de rosto (NBR 14724), e `docs/DroidServer_artigo_topicos.docx`, para a **Revista Tópicos**, sem capa nem folha de rosto (NBR 6022). As duas têm títulos e resumos em português e inglês, autoria e nota de minicurrículo. Edite sempre o vault, nunca os `.docx`.
>
> Edite aqui no vault e gere de novo; o que estiver destacado em amarelo no Word é lacuna a preencher (`[PENDENTE: ...]`, `[DEFINIR: ...]`). Títulos e autoria ficam em `META`, no `gerar.mjs`.
> Compatível com o **Word** e com o **WordCraft** (Linux): o arquivo passa na validação do esquema OOXML, não tem entradas de pasta no ZIP e a equação vai como imagem. Para equação nativa do Word: `EQUACOES=word npm run gerar`.

> [!note] Título
> "Servidor virtual privado" é usado no sentido do **modelo de serviço** (um ambiente Linux próprio, acessível pela rede e administrado como um servidor), e não no de virtualização de *hardware*: ver a seção 1.1 e o glossário. O sistema não tem escalonador, por isso o texto fala em **gerenciamento** de uma frota de aparelhos, e não em orquestração de *clusters*.

---

## Sumário

0. [Resumo / Abstract](00-resumo.md)
1. [Introdução](01-introducao.md) — contextualização; problema, questões de pesquisa e hipótese; objetivos; justificativa; escopo; organização
2. [Referencial Teórico](02-referencial-teorico.md)
3. [Trabalhos Relacionados](03-trabalhos-relacionados.md)
4. [Metodologia](04-metodologia.md)
5. [Prototipação e Implementação](05-prototipacao.md)
6. [Avaliação Experimental](06-avaliacao-experimental.md) — ambiente e versão avaliada, protocolo, resultados
7. [Discussão](07-discussao.md) — questões de pesquisa, hipótese, comparação, limitações e ameaças à validade
8. [Conclusão](08-conclusao.md) — com trabalhos futuros
- [Declaração de uso de IA](09-declaracao-ia.md)
- [Referências](10-referencias.md)
- [Glossário](11-glossario.md)

---

## Convenção de termos (usar igual em todo o texto)

| Termo | Significado no DroidServer | Evitar |
|---|---|---|
| **Host** | Computador que executa o servidor Flask (plano de controle) | "servidor" sem qualificação |
| **Node** (nó) | Um smartphone Android executando o agente `node.py` no Termux | chamar o celular de "Worker" |
| **Worker** | Um ambiente Linux (Alpine ou Debian) criado com `proot-distro` dentro de um Node e mantido pelo Supervisor | "container Docker" |
| **Tarefa** | Ordem enfileirada pelo Host (`criar_worker`, `deletar_worker`) e entregue ao Node no próximo *sync* | — |

## Status das notas

Em 19/11/2026 o texto foi enxugado (versão longa no *commit* 17f9f75). Em 24/11/2026 foi revisto com o parecer do orientador: os antigos capítulos 2 a 4 (problema, objetivos e justificativa) entraram na Introdução, as limitações e a resposta às questões de pesquisa foram para a nova seção de Discussão, e os arquivos foram renumerados. O que ainda depende do autor ou do orientador está em `docs/PROXIMOS-PASSOS.md` (seção 1).
