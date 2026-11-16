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

> [!note] Título
> O mesmo título está na capa e na folha de rosto do `docs/artigo_nao_finalizado.odt`. "Servidor virtual privado" é usado no sentido do **modelo de serviço** (um ambiente Linux próprio, acessível pela rede e administrado como um servidor), e não no de virtualização de *hardware*: ver a definição na seção 1.1 e o glossário.

---

## Sumário

0. [Resumo / Abstract](00-resumo.md) *(rascunho — depende dos resultados)*
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
   - 5.6 Modelos de Comunicação: Polling, WebSockets e Detecção de Falhas
   - 5.7 Pseudo-terminais e Supervisão de Processos
6. [Trabalhos Relacionados](06-trabalhos-relacionados.md)
7. [Metodologia](07-metodologia.md)
   - 7.1 Caracterização da Pesquisa
   - 7.2 Arquitetura Proposta do Sistema
   - 7.3 Ferramentas e Tecnologias Utilizadas
   - 7.4 Procedimentos de Implementação
8. [Prototipação e Implementação](08-prototipacao.md)
9. [Protocolo de Avaliação Experimental](09-avaliacao-experimental.md)
10. [Limitações, Ameaças à Validade e Trabalhos Futuros](10-limitacoes-e-trabalhos-futuros.md)
11. [Glossário](11-glossario.md)
12. [Referências](12-referencias.md)

---

## Convenção de termos (usar igual em todo o texto)

| Termo | Significado no DroidServer | Evitar |
|---|---|---|
| **Host** | Computador que executa o servidor Flask (plano de controle) | "servidor" sem qualificação |
| **Node** (nó) | Um smartphone Android executando o agente `node.py` no Termux | chamar o celular de "Worker" |
| **Worker** | Um ambiente Linux (Alpine ou Debian) criado com `proot-distro` dentro de um Node e mantido pelo Supervisor | "container Docker" |
| **Tarefa** | Ordem enfileirada pelo Host (`criar_worker`, `deletar_worker`) e entregue ao Node no próximo *sync* | — |

## Status das notas

| Nota | Situação |
|---|---|
| 00 Resumo | Rascunho com lacunas `[RESULTADO]` |
| 01–05 | Revisadas e ampliadas |
| 06 Trabalhos relacionados | Nova |
| 07 Metodologia | Revisada (antiga 06) |
| 08 Prototipação | Ampliada com a implementação real |
| 09 Avaliação | Nova — protocolo a executar |
| 10 Limitações | Nova |
| 11 Glossário | Nova |
| 12 Referências | Ampliada (antiga 08) |
