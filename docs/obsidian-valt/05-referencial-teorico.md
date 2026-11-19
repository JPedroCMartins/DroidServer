# 5. Referencial Teórico

## 5.1 Sistemas Distribuídos e Orquestração de Clusters

Um sistema distribuído é uma coleção de computadores independentes que se apresenta ao usuário como um sistema único e coerente (TANENBAUM; VAN STEEN, 2007), cujos componentes se coordenam apenas por troca de mensagens (COULOURIS et al., 2013). Para operar um *cluster*, costuma-se adotar o padrão controlador–trabalhador. O controlador forma o **plano de controle**: guarda o estado desejado, recebe os pedidos do administrador e distribui o trabalho. Os trabalhadores formam o **plano de dados** e executam as cargas. É o modelo do Borg e do Kubernetes, em que um agente em cada máquina reporta seu estado e o reconcilia com o desejado (VERMA et al., 2015; BURNS et al., 2016). O DroidServer usa uma versão simplificada em três níveis: **Host** (plano de controle), **Nodes** (smartphones com o agente) e **Workers** (ambientes Linux dentro de cada Node).

## 5.2 Computação de Borda (Edge Computing) e Mobile Cloud

A Computação de Borda leva processamento e armazenamento para perto de onde os dados são gerados, reduzindo latência e consumo de banda (SHI et al., 2016; SATYANARAYANAN, 2017). A Computação em Névoa propõe uma camada intermediária parecida (BONOMI et al., 2012). A *Mobile Cloud Computing* estudou como celulares transferem processamento para a nuvem (FERNANDO; LOKE; RAHAYU, 2013; DINH et al., 2013), e Satyanarayanan et al. (2009) propuseram os *cloudlets*, pequenos *data centers* próximos ao usuário. O DroidServer inverte o papel do smartphone, de consumidor para **provedor** de recursos, e pode ser visto como um *cloudlet* feito de aparelhos reaproveitados.

## 5.3 TI Verde (Green Computing) e Sustentabilidade

A TI Verde busca reduzir o impacto ambiental da tecnologia em todo o ciclo de vida (MURUGESAN, 2008). Isso inclui o carbono incorporado na fabricação, que nos smartphones domina as emissões (BELKHIR; ELMELIGI, 2018) e que a obsolescência desperdiça ao encurtar a vida útil (SLADE, 2006). O ganho do reúso foi quantificado em custo total de propriedade (SHAHRAD; WENTZLAFF, 2017) e em carbono por unidade de computação (SWITZER et al., 2023). Um ponto de atenção são as baterias de íon-lítio, que, mantidas sempre carregadas e aquecidas, degradam mais rápido e podem inchar (VETTER et al., 2005).

## 5.4 Arquitetura Android e Execução em Espaço de Usuário

O Android usa o *kernel* Linux, mas não tem a biblioteca C GNU (usa a Bionic), não oferece um *init* aos aplicativos e isola cada aplicativo em uma *sandbox* com UID próprio e SELinux (ANDROID OPEN SOURCE PROJECT, 2024a; SILBERSCHATZ; GALVIN; GAGNE, 2015). Sem *root*, o Docker não funciona, porque precisa criar *namespaces* e *cgroups* (MERKEL, 2014). O sistema também interrompe processos em segundo plano: o *Doze* adia rede e alarmes com o aparelho ocioso (ANDROID DEVELOPERS, 2024), o `lmkd` mata processos sob pressão de memória (ANDROID OPEN SOURCE PROJECT, 2024b) e o *phantom process killer*, desde o Android 12, limita a 32 os processos-filho de aplicativos (TERMUX, 2021).

O **Termux** é um emulador de terminal com um ambiente Linux mínimo, instalado na pasta do próprio aplicativo, sem *root* (FORNWALL, 2015). Sobre ele, o **PRoot** reimplementa em espaço de usuário o `chroot` e o `mount --bind` (VINCENT, 2014): com a chamada `ptrace`, intercepta as chamadas de sistema do processo e reescreve os caminhos de arquivo, simulando uma raiz (`/`) e um usuário `root` próprios dentro de uma pasta comum. O `proot-distro` automatiza a instalação de distribuições como Alpine e Debian sobre o PRoot. O udocker usa a mesma técnica para rodar contêineres sem privilégios em HPC (GOMES et al., 2018).

Em ARM64 sobre ARM64, o PRoot **não emula** instruções: o código roda direto no processador e só as chamadas de sistema são interceptadas. Também não isola CPU, memória, processos nem rede. O termo preciso é **execução em espaço de usuário com tradução de chamadas de sistema**.

## 5.5 Virtualização, Contêineres e PRoot

A virtualização clássica cria máquinas virtuais sob um *hypervisor* (POPEK; GOLDBERG, 1974). Os contêineres compartilham o *kernel* do hospedeiro e isolam processos com *namespaces* (o que cada um vê) e *cgroups* (quanto cada um consome) (SOLTESZ et al., 2007; RICE, 2020), com sobrecarga próxima de zero (FELTER et al., 2015). O PRoot ocupa uma terceira posição (Quadro 1).

| Característica | Máquina virtual | Contêiner (Docker) | PRoot (`proot-distro`) |
|---|---|---|---|
| Exige privilégio | Sim | Sim (ou *user namespaces*) | **Não** |
| *Kernel* | Próprio | Compartilhado | Compartilhado |
| Isolamento de arquivos | Total | *mount namespace* | Tradução de caminhos |
| Isolamento de processos e rede | Total | *namespaces* | **Nenhum** |
| Limite de recursos | Sim | *cgroups* | **Só `ulimit`** |
| Sobrecarga | Média a alta | Baixa | Alta com muitas chamadas de sistema |
| Funciona no Android sem *root* | Não | Não | **Sim** |

*Quadro 1 — Comparação entre técnicas de isolamento. Fonte: elaborado pelo autor com base em Felter et al. (2015), Gomes et al. (2018) e Vincent (2014).*

A sobrecarga do PRoot vem das trocas de contexto extras a cada chamada de sistema. Por isso, operações de arquivo pesam mais que cálculo puro, o que o experimento E3 mede.

## 5.6 Comunicação, Detecção de Falhas e Supervisão

No **polling** HTTP, o cliente consulta o servidor periodicamente. É simples e atravessa NAT porque a conexão parte do cliente, mas acrescenta até um intervalo de atraso (LORETO et al., 2011). O **WebSocket** abre um canal TCP persistente e bidirecional, adequado a tempo real (FETTE; MELNIKOV, 2011). A biblioteca Socket.IO acrescenta reconexão e *heartbeats*. Como não se distingue com certeza um nó lento de um nó falho, usam-se detectores de falha baseados em *timeouts* (CHANDRA; TOUEG, 1996). O DroidServer usa o próprio *sync* periódico como *heartbeat* e marca como *Offline* o Node que fica mais de 25 s sem contato.

Um **pseudo-terminal** (PTY) é um par de dispositivos virtuais que simula um terminal físico: o *shell* ligado a um lado acha que está em um terminal real, e o programa do outro lado lê a saída e injeta as teclas (KERRISK, 2010). No navegador, o xterm.js desenha o terminal. Como o Android não oferece `systemd`, os serviços são mantidos pelo **Supervisor**, que inicia, monitora e reinicia processos descritos em blocos `[program:x]` (SUPERVISOR, 2024).
