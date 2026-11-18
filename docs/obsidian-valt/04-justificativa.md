# 4. Justificativa

## 4.1 Relevância ambiental

A principal motivação deste trabalho reside na intersecção entre a TI Verde e a engenharia de sistemas distribuídos. A geração de lixo eletrônico cresce cinco vezes mais rápido do que a reciclagem documentada (BALDÉ et al., 2024), e a maior parte da pegada de carbono de um smartphone concentra-se na fabricação, não no uso: Belkhir e Elmeligi (2018) estimam que, com a vida útil média de dois anos, a fabricação responde por 85% a 95% da pegada de carbono anual desses aparelhos. Prolongar a vida útil de um dispositivo já fabricado é, portanto, uma das formas mais efetivas de reduzir seu impacto, o que Switzer et al. (2023) formalizam com a métrica de Intensidade de Carbono Computacional (*Computational Carbon Intensity* — CCI), segundo a qual smartphones reaproveitados apresentam o melhor potencial entre servidores antigos, *laptops* e telefones.

## 4.2 Relevância econômica e social

Pequenos desenvolvedores, pesquisadores, estudantes e organizações com poucos recursos frequentemente não conseguem manter instâncias de servidores em nuvem para hospedar microsserviços, *bots* ou APIs leves. Um *cluster* formado por smartphones antigos, já disponíveis em gavetas ou doados, oferece uma infraestrutura de custo de aquisição praticamente nulo para ensino de sistemas distribuídos, laboratórios de redes e serviços internos.

## 4.3 Relevância técnica e científica

Do ponto de vista técnico, o trabalho enfrenta a rigidez do Android — que impede a conteinerização nativa sem acesso privilegiado — utilizando execução em espaço de usuário (PRoot) para provisionar ambientes Linux de forma orquestrada e automatizada. A literatura sobre *clusters* de smartphones (MARINELLI, 2009; ARSLAN et al., 2012; BÜSCHING; SCHILDT; WOLF, 2012) concentra-se em computação paralela ou em *frameworks* específicos, e as propostas mais recentes (SHAHRAD; WENTZLAFF, 2017; SWITZER et al., 2023) pressupõem, em geral, aparelhos com sistema substituído ou acesso privilegiado. Há, portanto, espaço para investigar uma abordagem que preserve o *firmware* original e ofereça ao usuário a abstração familiar de um VPS (ver [06 — Trabalhos relacionados](06-trabalhos-relacionados.md)).

## 4.4 Relevância regional

O reúso de smartphones já foi aplicado com sucesso na própria Amazônia: o projeto *Rainforest Connection* instala celulares reciclados, alimentados por energia solar, nas copas das árvores para detectar acusticamente motosserras e atividades de desmatamento ilegal (RAINFOREST CONNECTION, 2014). O exemplo mostra que aparelhos descartados podem atuar como infraestrutura de borda em regiões com conectividade e orçamento limitados — realidade de muitas instituições de ensino e de pequenas empresas de Manaus e do interior do Amazonas. Além disso, a Política Nacional de Resíduos Sólidos (BRASIL, 2010) e o decreto que regulamenta a logística reversa de eletroeletrônicos (BRASIL, 2020) colocam a extensão do ciclo de vida desses produtos como responsabilidade compartilhada, à qual iniciativas de reúso como esta se alinham.
