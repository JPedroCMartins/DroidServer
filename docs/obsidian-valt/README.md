# **DroidServer: orquestração de servidores virtuais privados em smartphones Android reaproveitados**

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
> `docs/DroidServer_TCC_artigo.docx` é gerado a partir destas notas (`cd docs/gerador-docx && npm install && npm run gerar`), no formato ABNT de artigo. Edite aqui no vault e gere de novo; o que estiver destacado em amarelo no Word é lacuna a preencher.
> Compatível com o **Word** e com o **WordCraft** (Linux): o arquivo passa na validação do esquema OOXML, não tem entradas de pasta no ZIP e a equação vai como imagem (o WordCraft ainda não tem editor de equações). Para equação nativa do Word: `EQUACOES=word npm run gerar`.

> [!note] Título
> O mesmo título está na capa e na folha de rosto do `docs/DroidServer_TCC_artigo.docx`, gerado a partir destas notas. "Servidor virtual privado" é usado no sentido do **modelo de serviço** (um ambiente Linux próprio, acessível pela rede e administrado como um servidor), e não no de virtualização de *hardware*: ver a definição na seção 1.1 e o glossário.

---

## Sumário

0. [Resumo / Abstract](00-resumo.md) *(preenchido)*
1. [Introdução](01-introducao.md)
   - 1.1 Contextualização
   - 1.2 Limites do Trabalho (Escopo e Delimitação)
   - 1.3 Organização do Trabalho
2. [Problema de Pesquisa](02-problema-de-pesquisa.md)
   - 2.1 Hipótese
3. [Objetivos](03-objetivos.md)
   - 3.1 Objetivo Geral
   - 3.2 Objetivos Específicos
4. [Justificativa](04-justificativa.md)
   - 4.1 Relevância ambiental
   - 4.2 Relevância econômica e social
   - 4.3 Relevância técnica e científica
   - 4.4 Relevância regional
5. [Referencial Teórico](05-referencial-teorico.md)
   - 5.1 Sistemas Distribuídos e Orquestração de Clusters
   - 5.2 Computação de Borda (Edge Computing) e Mobile Cloud
   - 5.3 TI Verde (Green Computing) e Sustentabilidade
   - 5.4 Arquitetura Android e Execução em Espaço de Usuário
   - 5.5 Virtualização, Contêineres e PRoot
   - 5.6 Comunicação, Detecção de Falhas e Supervisão
6. [Trabalhos Relacionados](06-trabalhos-relacionados.md)
7. [Metodologia](07-metodologia.md)
   - 7.1 Caracterização da Pesquisa
   - 7.2 Arquitetura Proposta do Sistema
   - 7.3 Ferramentas e Tecnologias Utilizadas
   - 7.4 Procedimentos de Implementação
8. [Prototipação e Implementação](08-prototipacao.md)
9. [Avaliação Experimental](09-avaliacao-experimental.md)
10. [Limitações, Ameaças à Validade e Trabalhos Futuros](10-limitacoes-e-trabalhos-futuros.md)
11. [Conclusão](11-conclusao.md)
    - 11.1 Respostas às questões de pesquisa
    - 11.2 Hipótese
    - 11.3 Contribuições e considerações finais
12. [Referências](12-referencias.md)
13. [Glossário](13-glossario.md)

---

## Convenção de termos (usar igual em todo o texto)

| Termo | Significado no DroidServer | Evitar |
|---|---|---|
| **Host** | Computador que executa o servidor Flask (plano de controle) | "servidor" sem qualificação |
| **Node** (nó) | Um smartphone Android executando o agente `node.py` no Termux | chamar o celular de "Worker" |
| **Worker** | Um ambiente Linux (Alpine ou Debian) criado com `proot-distro` dentro de um Node e mantido pelo Supervisor | "container Docker" |
| **Tarefa** | Ordem enfileirada pelo Host (`criar_worker`, `deletar_worker`) e entregue ao Node no próximo *sync* | — |

## Status das notas

Em 19/11/2026 o texto foi enxugado para o essencial (o .docx passou de 53 para 29 páginas): saíram os detalhes de implementação do capítulo 8, três das cinco capturas do painel e o detalhamento dos experimentos do capítulo 9, que ficou com uma tabela-resumo e duas figuras. A versão longa está no histórico do Git (commit 17f9f75).

| Nota | Situação |
|---|---|
| 00 Resumo | Preenchido com os resultados, inclusive a E7 |
| 01–07 | Enxutas (19/11) |
| 08 Prototipação | Enxuta: arquitetura, protocolo, ciclo de vida, monitoramento, decisões e 2 capturas |
| 09 Avaliação | Executada em 16 e 17/11; resumida em uma tabela e 2 figuras |
| 10 Limitações | Enxuta |
| 11 Conclusão | Enxuta |
| 12 Referências | Só obras citadas |
| 13 Glossário | Nova (era a 11) |
