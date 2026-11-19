# 1. Introdução

## 1.1 Contextualização

A demanda por mais desempenho e as práticas de obsolescência programada e percebida (SLADE, 2006) fazem crescer o lixo eletrônico (*e-waste*). Em 2022, o mundo gerou 62 milhões de toneladas de resíduos eletroeletrônicos, 82% a mais que em 2010, e só 22,3% foram coletados e reciclados de forma adequada (BALDÉ et al., 2024). Cerca de 1,5 bilhão de smartphones são vendidos por ano, e a maioria é descartada em menos de dois anos (SWITZER et al., 2023).

Muitos desses aparelhos saem de uso por falhas periféricas, como tela quebrada, bateria gasta ou fim das atualizações, enquanto o processador ARM *multicore*, a memória e o armazenamento continuam funcionando. Mesmo aparelhos antigos têm capacidade compatível com microsserviços modernos (SWITZER et al., 2023), e como a energia de fabricação domina o consumo ao longo da vida útil, reaproveitá-los é vantajoso (SHAHRAD; WENTZLAFF, 2017). A Computação de Borda (*Edge Computing*), que leva o processamento para perto de onde os dados são gerados (SATYANARAYANAN, 2017; SHI et al., 2016), é um destino natural para esse recurso ocioso.

Este trabalho apresenta o **DroidServer**, um protótipo que reúne smartphones Android sem acesso *root* em um pequeno *cluster* gerenciado por um servidor central. Cada aparelho roda um agente em Python no Termux, que cria ambientes Linux com `proot-distro`, mantém esses ambientes como serviços supervisionados e envia métricas ao servidor. O administrador opera tudo por um painel web, que inclui um terminal no navegador.

Aqui, **servidor virtual privado** (VPS) designa o **modelo de serviço** que cada Worker oferece: um ambiente Linux próprio, com arquivos, pacotes e serviços independentes, acessível pela rede e administrado como um servidor. Não há virtualização de *hardware* nem isolamento pelo *kernel*. Os Workers compartilham o *kernel*, a rede, a CPU e a memória do aparelho, e o isolamento se limita ao sistema de arquivos, obtido pelo PRoot (seção 5). Os custos dessa escolha são medidos no capítulo 9.

## 1.2 Limites do Trabalho (Escopo e Delimitação)

O trabalho se limita a um protótipo no modelo Host-Node-Worker (ver [Convenção de termos](README.md)), que cria ambientes Alpine e Debian usando só o Termux e o PRoot, **sem** *root*, desbloqueio de *bootloader* ou ROM customizada, e que hospeda cargas leves (APIs, *bots*, automações) em **rede local**. Ficam de fora: solução comercial ou multilocação com isolamento de segurança entre usuários; cargas pesadas e contínuas, por causa dos limites térmicos e do *Low Memory Killer* do Android; agendamento automático e migração de Workers entre aparelhos; alta disponibilidade do Host; armazenamento distribuído; e exposição à Internet pública.

## 1.3 Organização do Trabalho

Os capítulos 2 a 4 apresentam o problema, os objetivos e a justificativa. O capítulo 5 traz o referencial teórico, e o 6, os trabalhos relacionados. O capítulo 7 descreve a metodologia, o 8, o protótipo, e o 9, a avaliação e os resultados. O capítulo 10 discute as limitações, e o 11 conclui.
