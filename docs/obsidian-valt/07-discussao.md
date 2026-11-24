# 7. Discussão

## 7.1 Questões de pesquisa

**QP1 — Isolamento.** É possível rodar distribuições Linux completas no Android sem *root*: um Worker Alpine instala em 1,9 s e ocupa 9 MB. O custo depende da carga. Cálculo e escrita sequencial quase não perdem desempenho, mas operações sobre caminhos de arquivo ficam até 13× mais lentas, e uma API HTTP entrega 40% a 45% da vazão nativa com concorrência. Serviços de rede e de CPU sofrem pouco; compilação e instalação de pacotes, mais. O isolamento é só do sistema de arquivos, o que basta para separar ambientes de um mesmo administrador, mas não para hospedar terceiros. Esta questão foi **respondida**.

**QP2 — Gerenciamento e redes.** *Polling* iniciado pelo Node para o controle e WebSocket para o tempo real funcionaram: identificar os Nodes por *token* absorveu as trocas de IP por DHCP, e o painel pôde ser desligado sem afetar os serviços. O *polling* de 10 s domina o tempo percebido (um Worker aparece no painel em 16 s), e o terminal só atingiu p95 de 58 ms depois de passar a usar WebSocket direto, e só em 5 GHz. A segunda parte da questão, a tolerância às interrupções do Android, **não foi testada**: os aparelhos ficaram na tomada, com a otimização de bateria desativada e o *wake-lock* ativo, e o *Doze* não chega a ser acionado nessas condições. A QP2 foi, portanto, **respondida parcialmente**.

**QP3 — Recursos e estabilidade.** O DroidServer consome pouco: cerca de 20 MB de RAM no agente e menos de 2% da CPU do aparelho. No moto e40, o serviço de demonstração ficou 99,94% disponível em 24 h, sem nenhum reinício. Energia e temperatura **não foram medidas**, porque os dois aparelhos negam a leitura dos sensores sem *root*, e a carga contínua foi leve. A QP3 também foi **respondida parcialmente**, e pelo mesmo motivo o OE5 foi cumprido só em parte.

## 7.2 Hipótese

As condições (a) comunicação iniciada pelo aparelho e (b) supervisão dos processos foram implementadas e se mostraram suficientes: o modelo *pull* absorveu trocas de IP e desligamentos do Host, e o serviço ficou no ar as 24 h. O critério de disponibilidade (≥ 99%) foi atendido. O de latência (p95 ≤ 200 ms) foi atendido em 5 GHz, mas **não** em 2,4 GHz, a rede em que os Nodes operaram nos demais experimentos. Como os dois critérios eram exigidos, a **H1 é confirmada apenas parcialmente**: vale para a disponibilidade e, quanto à latência, só em redes de 5 GHz. A falha em 2,4 GHz se deve ao meio sem fio, e não ao DroidServer, mas é uma condição real de uso que o sistema não controla.

Sobre a condição (c), como a comparação com o Android em configuração padrão não foi feita, não se pode afirmar que desativar as otimizações de bateria é necessário, apenas que é suficiente no aparelho testado.

## 7.3 Comparação com os trabalhos relacionados

Diferentemente do Junkyard Computing (SWITZER et al., 2023) e do DroidCluster (BÜSCHING; SCHILDT; WOLF, 2012), o DroidServer não troca nem modifica o sistema do aparelho, e paga isso em desempenho: sem *namespaces* e *cgroups*, a tradução de chamadas de sistema do PRoot custa até 13× em operações de arquivo, enquanto contêineres têm sobrecarga próxima de zero (FELTER et al., 2015). Em troca, qualquer aparelho com Termux pode ser usado, sem desbloqueio de *bootloader*. Diferentemente do UserLAnd, do Andronix e do `proot-distro` usado sozinho, o DroidServer gerencia vários aparelhos a partir de um Host e mantém os ambientes como serviços supervisionados, o que a E7 mostrou ser estável por 24 h.

## 7.4 Limitações

- **Isolamento fraco:** os Workers compartilham rede, processos, CPU e memória entre si e com o Termux, e sem *cgroups* o único limite é o `ulimit`. Um Worker pode esgotar o aparelho. Por isso, "servidor virtual privado" vale como modelo de serviço, e não como garantia de isolamento.
- **Restrições do Android sem *root*:** a CPU medida cobre só os processos do Termux, e temperatura e bateria não são legíveis. O *Doze*, o `lmkd` e o *phantom process killer* podem encerrar o agente, e as mitigações exigem configuração manual.
- **Segurança:** a senha do painel é opcional e vem desligada; não há TLS, então senha e *tokens* trafegam em claro; e um Node ainda não pareado aceita pareamento de qualquer máquina da rede local. O uso se restringe a uma LAN confiável.
- **Gerenciamento centralizado e manual:** o Host não é replicado e não há escalonador. Sem o Host, os serviços continuam rodando, mas não se cria nem remove Workers.
- **Distribuições:** só Alpine e Debian, que têm imagens oficiais para ARM64.

## 7.5 Ameaças à validade

**Validade de construto.** A E7 mede a disponibilidade do processo, pelo `GET` local feito pelo próprio agente, e não a alcançabilidade do serviço pela rede. Uma amostra ausente conta como falha, o que torna a medida conservadora, mas um serviço vivo e inalcançável pelo Wi-Fi contaria como disponível. A detecção de Node *offline* foi avaliada por projeto, e não medida (E6).

**Validade interna.** As variações do Wi-Fi e os processos de outros aplicativos, que a métrica de CPU não enxerga, afetam os tempos. Na E7 e, portanto, na E10, rodaram ao mesmo tempo outro Worker com um *site* e, a partir da 14ª hora, testes de um túnel e de um Worker Debian, o que pesa sobre a CPU e a memória relatadas. Durante a E8, o Node 2 instalava pacotes no mesmo Wi-Fi.

**Validade externa.** Foram só dois aparelhos, e cada experimento rodou em um deles (Quadro 3); cada fabricante tem políticas de bateria próprias. As principais ameaças descritas na seção 1.2 não foram exercitadas: com o aparelho na tomada e a otimização de bateria desativada, o *Doze* não entra, e o Android 11 do Node 2 não tem o *phantom process killer*, introduzido no Android 12. A comparação com o Android em configuração padrão não foi feita. Os resultados valem, portanto, para aparelhos na tomada e configurados como na seção 6.1.

**Confiabilidade.** Para permitir a replicação, os *scripts*, os dados brutos e as notas de método estão no repositório, com o *commit* de cada experimento (seção 6.1).
