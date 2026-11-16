# 1. Introdução

## 1.1 Contextualização

O avanço acelerado da indústria de dispositivos móveis, impulsionado pela demanda por maior capacidade de processamento e por práticas de obsolescência programada e percebida (SLADE, 2006), tem gerado um volume crescente de lixo eletrônico (*e-waste*) em escala global. Segundo o *Global E-waste Monitor 2024*, o mundo gerou 62 milhões de toneladas de resíduos eletroeletrônicos em 2022 — um aumento de 82% em relação a 2010 —, e apenas 22,3% desse total foi documentado como coletado e reciclado de forma ambientalmente adequada; a projeção é de 82 milhões de toneladas em 2030 (BALDÉ et al., 2024). Estima-se ainda que cerca de 1,5 bilhão de smartphones sejam vendidos por ano e que a maior parte deles seja descomissionada em menos de dois anos (SWITZER et al., 2023).

Smartphones são frequentemente descartados ou subutilizados por falhas periféricas — telas quebradas, baterias degradadas, portas de carregamento danificadas — ou simplesmente por deixarem de receber atualizações, embora seus componentes centrais, como processadores *multicore* de arquitetura ARM, memória RAM e armazenamento *flash*, permaneçam operacionais e capazes de executar tarefas computacionais relevantes. Trabalhos recentes argumentam que mesmo aparelhos com uma década de uso possuem capacidade compatível com a demanda de microsserviços modernos em nuvem (SWITZER et al., 2023) e que sua energia de fabricação domina o consumo ao longo da vida útil, o que torna o reúso vantajoso do ponto de vista energético (SHAHRAD; WENTZLAFF, 2017).

Paralelamente, o paradigma da computação em nuvem tem expandido suas fronteiras em direção à Computação de Borda (*Edge Computing*), que desloca processamento e armazenamento para perto de onde os dados são gerados (SATYANARAYANAN, 2017; SHI et al., 2016). Nesse cenário, dispositivos móveis ociosos representam um recurso computacional latente, capaz de atuar como nós de processamento descentralizados e formar *clusters* de baixo custo que se comportam como Servidores Virtuais Privados (*Virtual Private Servers* — VPS) encontrados em provedores tradicionais.

Este trabalho apresenta o **DroidServer**, um protótipo de orquestração que reúne smartphones Android sem acesso *root* em um pequeno *cluster* gerenciado por um servidor central. Cada aparelho executa um agente em Python dentro do Termux, que provisiona ambientes Linux isolados com `proot-distro`, mantém esses ambientes como serviços supervisionados e reporta métricas ao servidor; o administrador opera tudo por um painel web, incluindo um terminal interativo no navegador.

## 1.2 Limites do Trabalho (Escopo e Delimitação)

Para garantir a viabilidade da pesquisa e a precisão da avaliação, este projeto restringe-se ao desenvolvimento e à análise de um protótipo de orquestração no modelo Host-Node-Worker (ver [Convenção de termos](README.md)).

O trabalho limita-se a:

- Implementar a comunicação de rede e o provisionamento de ambientes isolados (Alpine e Debian) utilizando exclusivamente o Termux e o PRoot (via `proot-distro`), **sem** acesso *root*, desbloqueio de *bootloader* ou ROMs customizadas nos aparelhos.
- Desenvolver a camada de controle (Host) focada na distribuição de tarefas e no monitoramento de estado via HTTP e WebSockets.
- Hospedar e orquestrar cargas de trabalho leves (microsserviços, *bots*, APIs e automações simples) em uma **rede local** (LAN).

O trabalho **não** abrangerá:

- O desenvolvimento de uma solução comercial escalável para clientes externos, nem multilocação (*multi-tenancy*) com isolamento de segurança entre usuários.
- A execução de aplicações de alto custo computacional sustentado (como mineração de criptomoedas ou treinamento de redes neurais profundas), devido às limitações térmicas de hardware sem resfriamento ativo e à atuação do gerenciador de memória do Android (*Low Memory Killer*).
- O agendamento automático de cargas entre nós (*scheduling*), a migração de *workers* entre aparelhos e a alta disponibilidade do próprio Host.
- A integração de armazenamento persistente distribuído (como Ceph ou GlusterFS) entre os nós.
- A exposição dos serviços à Internet pública (NAT, *tunneling*, TLS), tratada como trabalho futuro.

## 1.3 Organização do Trabalho

Além desta introdução, o Capítulo 2 apresenta o problema de pesquisa e a hipótese; o Capítulo 3, os objetivos; o Capítulo 4, a justificativa. O Capítulo 5 reúne o referencial teórico e o Capítulo 6, os trabalhos relacionados. O Capítulo 7 descreve a metodologia; o Capítulo 8, a arquitetura e a implementação do protótipo; e o Capítulo 9, o protocolo de avaliação e os resultados. O Capítulo 10 discute limitações, ameaças à validade e trabalhos futuros.
