# 5. Referencial Teórico

Este capítulo apresenta os conceitos que embasam a pesquisa: dos princípios de sistemas distribuídos às particularidades do Android, passando por virtualização, comunicação em rede e controle de processos.

## 5.1 Sistemas Distribuídos e Orquestração de Clusters

Um sistema distribuído é uma coleção de computadores independentes que se apresenta aos seus usuários como um sistema único e coerente (TANENBAUM; VAN STEEN, 2007). Seus componentes, localizados em computadores interligados em rede, comunicam-se e coordenam suas ações apenas por troca de mensagens (COULOURIS et al., 2013). Os objetivos dessa arquitetura incluem o compartilhamento de recursos, a transparência, a escalabilidade e a tolerância a falhas. Um *cluster* computacional é um conjunto de nós interconectados que atuam em conjunto na execução de tarefas.

Para operar um *cluster*, adota-se frequentemente o padrão controlador–trabalhador (*controller–worker*, historicamente chamado de mestre–escravo). O nó controlador forma o **plano de controle** (*control plane*): mantém o estado desejado do sistema, recebe requisições do administrador e distribui o trabalho. Os nós trabalhadores formam o **plano de dados** (*data plane*) e executam as cargas delegadas. Esse é o modelo de sistemas como Borg e Kubernetes, nos quais um agente em cada máquina (o *kubelet*, no Kubernetes) reporta periodicamente seu estado e reconcilia o estado real com o desejado (VERMA et al., 2015; BURNS et al., 2016).

O DroidServer adota uma versão simplificada desse modelo em três níveis: o **Host** (plano de controle), os **Nodes** (smartphones com o agente) e os **Workers** (ambientes Linux dentro de cada Node).

## 5.2 Computação de Borda (Edge Computing) e Mobile Cloud

O modelo de Computação em Nuvem centralizou o processamento em grandes *data centers*. A proliferação de dispositivos de Internet das Coisas (IoT) e o volume de dados gerados nas extremidades da rede, contudo, motivaram a Computação de Borda: um paradigma que desloca processamento e armazenamento para perto de onde os dados são gerados ou consumidos, reduzindo latência e consumo de banda (SHI et al., 2016; SATYANARAYANAN, 2017). A Computação em Névoa (*Fog Computing*) propõe uma camada intermediária semelhante entre os dispositivos e a nuvem (BONOMI et al., 2012).

A *Mobile Cloud Computing* (MCC) estudou inicialmente como dispositivos móveis podem transferir (*offload*) processamento para a nuvem (FERNANDO; LOKE; RAHAYU, 2013; DINH et al., 2013). Satyanarayanan et al. (2009) propuseram os *cloudlets*: pequenos *data centers* próximos ao usuário, acessíveis por rede local com baixa latência. O DroidServer inverte o papel tradicional do smartphone — de consumidor para **provedor** de recursos — e pode ser entendido como um *cloudlet* construído com aparelhos reaproveitados.

## 5.3 TI Verde (Green Computing) e Sustentabilidade

A TI Verde é o campo que busca minimizar o impacto ambiental do projeto, da fabricação, do uso e do descarte de tecnologias da informação (MURUGESAN, 2008). A sustentabilidade de infraestruturas computacionais não se restringe à eficiência energética (desempenho por watt): engloba também o carbono incorporado (*embodied carbon*) na fabricação, que no caso dos smartphones domina as emissões do ciclo de vida (BELKHIR; ELMELIGI, 2018).

A obsolescência — planejada ou percebida — encurta esse ciclo (SLADE, 2006). Dispositivos descartados por danos periféricos (telas, baterias) mantêm intactos o processador, a memória e o armazenamento. Reaproveitá-los como infraestrutura para microsserviços reduz a necessidade de fabricar novos servidores de pequeno porte, argumento quantificado por Shahrad e Wentzlaff (2017) em termos de custo total de propriedade e por Switzer et al. (2023) em termos de carbono por unidade de computação.

Há, porém, um ponto de atenção para a avaliação: baterias de íon-lítio mantidas permanentemente carregadas e aquecidas degradam-se mais rápido e podem inchar (VETTER et al., 2005). Um *cluster* de smartphones deve, portanto, considerar o controle de carga ou a remoção da bateria quando possível.

## 5.4 Arquitetura Android e Execução em Espaço de Usuário

Embora o Android seja construído sobre o *kernel* Linux, sua arquitetura difere das distribuições GNU/Linux tradicionais: não há a biblioteca C GNU (usa-se a Bionic), não há um sistema de *init* acessível aos aplicativos e cada aplicativo executa em uma *sandbox* com UID próprio, reforçada por políticas obrigatórias do SELinux (ANDROID OPEN SOURCE PROJECT, 2024a; SILBERSCHATZ; GALVIN; GAGNE, 2015). O acesso privilegiado (*root*) às camadas inferiores é bloqueado ao usuário comum.

Essa restrição inviabiliza motores de conteinerização padrão, como o Docker, que precisam de privilégios para criar *namespaces* e *cgroups* (MERKEL, 2014). Além disso, o Android aplica políticas agressivas de gerenciamento de recursos:

- **Doze e App Standby** (desde o Android 6.0): adiam *jobs*, alarmes e acesso à rede quando o aparelho está ocioso (ANDROID DEVELOPERS, 2024);
- **Low Memory Killer** (`lmkd`): encerra processos com base na pressão de memória e na prioridade (`oom_score_adj`) (ANDROID OPEN SOURCE PROJECT, 2024b);
- **Phantom process killer** (desde o Android 12): limita a 32 o número de processos-filho de aplicativos e encerra os que usam CPU excessiva em segundo plano (TERMUX, 2021).

O **Termux** é um emulador de terminal com um ambiente Linux mínimo, compilado para a Bionic e instalado no diretório de dados do próprio aplicativo, sem exigir *root* (FORNWALL, 2015). Sobre ele, o **PRoot** reimplementa em espaço de usuário funcionalidades como `chroot`, `mount --bind` e `binfmt_misc` (VINCENT, 2014). Ele usa a chamada de sistema `ptrace` para interceptar as chamadas de sistema do processo rastreado e reescrever caminhos de arquivo, criando a ilusão de um sistema de arquivos raiz (`/`) próprio e de um usuário `root` falso dentro de um diretório comum. O `proot-distro` automatiza o download e a configuração de *rootfs* de distribuições (Alpine, Debian etc.) sobre o PRoot. Abordagem semelhante é usada fora do Android pelo udocker, que executa contêineres sem privilégios em ambientes de HPC tendo o PRoot como motor padrão (GOMES et al., 2018).

> [!important] PRoot não é emulação nem contêiner no sentido estrito
> Na arquitetura nativa (ARM64 em ARM64), o PRoot **não emula** instruções: o código executa diretamente no processador, e apenas as chamadas de sistema são interceptadas. Só há emulação quando se combina o PRoot com o QEMU para executar binários de outra arquitetura. Também não há isolamento de recursos (CPU, memória) nem de processos e rede como em um contêiner com *namespaces* e *cgroups*: um Worker enxerga a mesma pilha de rede e os mesmos processos do Termux. O termo mais preciso é **execução em espaço de usuário com tradução de chamadas de sistema** (*user-space chroot*).

## 5.5 Virtualização, Contêineres e PRoot

A virtualização clássica cria máquinas virtuais equivalentes ao hardware real, sob controle de um monitor (*hypervisor*) (POPEK; GOLDBERG, 1974). A virtualização em nível de sistema operacional — os contêineres — compartilha o *kernel* do hospedeiro e isola grupos de processos com *namespaces* (o que cada processo vê) e *cgroups* (quanto cada processo pode consumir) (SOLTESZ et al., 2007; RICE, 2020). Contêineres têm sobrecarga próxima de zero em CPU e memória quando comparados à execução nativa (FELTER et al., 2015) e popularizaram-se com o Docker (MERKEL, 2014) e com orquestradores como o Kubernetes (BURNS et al., 2016).

O PRoot ocupa uma terceira posição. O Quadro 1 compara as abordagens:

| Característica | Máquina virtual | Contêiner (Docker) | PRoot (`proot-distro`) |
|---|---|---|---|
| Exige privilégio | Sim (hipervisor) | Sim (ou *user namespaces*) | **Não** |
| *Kernel* | Próprio | Compartilhado | Compartilhado |
| Isolamento de sistema de arquivos | Total | *mount namespace* | Tradução de caminhos (`ptrace`) |
| Isolamento de processos e rede | Total | *PID/net namespaces* | **Nenhum** |
| Limite de recursos | Sim | *cgroups* | **Nenhum** (apenas `ulimit`) |
| Sobrecarga | Média a alta | Baixa | Alta em operações com muitas chamadas de sistema |
| Disponível no Android sem *root* | Não | Não | **Sim** |

*Quadro 1 — Comparação entre técnicas de isolamento. Fonte: elaborado pelo autor com base em Felter et al. (2015), Gomes et al. (2018) e Vincent (2014).*

A sobrecarga do PRoot decorre de cada chamada de sistema gerar trocas de contexto adicionais entre o processo rastreado e o rastreador; cargas intensivas em E/S de arquivos (instalação de pacotes, compilação) são as mais afetadas, enquanto cargas limitadas por CPU sofrem pouco. Medir essa sobrecarga é um dos experimentos propostos (ver [09](09-avaliacao-experimental.md)).

## 5.6 Modelos de Comunicação: Polling, WebSockets e Detecção de Falhas

No **polling** HTTP, o cliente consulta periodicamente o servidor em busca de novidades. A técnica é simples e atravessa NAT e *firewalls* porque a conexão é sempre iniciada pelo cliente, mas introduz latência de até um intervalo de consulta e tráfego ocioso. O *long polling* mantém a requisição aberta até haver dados, reduzindo a latência à custa de recursos no servidor (LORETO et al., 2011).

O protocolo **WebSocket** estabelece, a partir de um *handshake* HTTP, um canal TCP persistente e *full-duplex* entre cliente e servidor, adequado a comunicação em tempo real (FETTE; MELNIKOV, 2011). A biblioteca Socket.IO acrescenta reconexão automática, *heartbeats* (`ping_interval`/`ping_timeout`) e *fallback* para *long polling* via Engine.IO.

Em sistemas assíncronos, não é possível distinguir com certeza um nó lento de um nó falho; utilizam-se **detectores de falha não confiáveis** baseados em *heartbeats* e *timeouts* (CHANDRA; TOUEG, 1996). O DroidServer usa o próprio *sync* periódico como *heartbeat*: um Node sem contato por mais de 25 s é marcado como *Offline* e, após 180 s sem tarefas pendentes, removido do painel. A escolha desses valores equilibra a rapidez de detecção e a ocorrência de falsos positivos causados pelo Doze e por oscilações de Wi-Fi.

O modelo *pull* (o nó busca suas ordens) é o mesmo usado por agentes de gerência de configuração e pelo *kubelet*; ele é especialmente adequado a nós móveis porque dispensa que o Host conheça o endereço do nó ou abra conexões até ele.

## 5.7 Pseudo-terminais e Supervisão de Processos

Um **pseudo-terminal** (PTY) é um par de dispositivos virtuais — mestre e escravo — que emula um terminal físico: o processo ligado ao lado escravo (um *shell*, por exemplo) comporta-se como se estivesse em um terminal real, enquanto o programa que controla o lado mestre lê sua saída e injeta entradas (KERRISK, 2010). É o mecanismo usado por emuladores de terminal, pelo `ssh` e pelo `tmux`. O tamanho da janela é informado ao processo pela `ioctl` `TIOCSWINSZ`, o que permite que programas como `vim` e `htop` se redesenhem corretamente. No navegador, o xterm.js interpreta as sequências de escape ANSI e desenha o terminal.

Para manter serviços de longa duração, sistemas Linux usam gerenciadores como o `systemd`. Como o Android não oferece um *init* aos aplicativos, o DroidServer utiliza o **Supervisor**, um sistema cliente-servidor em Python que inicia, monitora e reinicia processos descritos em arquivos de configuração `[program:x]` (SUPERVISOR, 2024).
