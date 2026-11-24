# Glossário

| Termo | Definição |
|---|---|
| **Bionic** | Biblioteca C do Android, usada no lugar da glibc. |
| **cgroups** | Recurso do *kernel* Linux que limita e contabiliza o uso de CPU, memória e E/S por grupo de processos. |
| **Cloudlet** | Pequeno *data center* próximo ao usuário, acessível com baixa latência (Satyanarayanan *et al.*, 2009). |
| **Control plane** | Plano de controle; parte do sistema que decide e coordena (no DroidServer, o Host). |
| **Doze** | Modo de economia de energia do Android que adia rede e CPU de aplicativos quando o aparelho está ocioso. |
| **E-waste** | Lixo eletrônico; resíduos de equipamentos eletroeletrônicos. |
| **Heartbeat** | Mensagem periódica que indica que um nó está vivo. |
| **Host** | Servidor central do DroidServer (Flask + Socket.IO). |
| **lmkd** | *Low Memory Killer daemon*; encerra processos do Android sob pressão de memória. |
| **Namespace** | Recurso do *kernel* Linux que isola o que um processo enxerga (PIDs, rede, pontos de montagem, usuários). |
| **Node** | Smartphone Android que executa o agente do DroidServer. |
| **Phantom process killer** | Mecanismo do Android 12+ que encerra processos-filho de aplicativos acima de um limite ou com CPU excessiva. |
| **Polling** | Consulta periódica de um cliente ao servidor. |
| **PRoot** | Implementação em espaço de usuário de `chroot`, `mount --bind` e `binfmt_misc` baseada em `ptrace`. |
| **proot-distro** | Utilitário do Termux que instala e gerencia distribuições Linux sobre o PRoot. |
| **ptrace** | Chamada de sistema que permite a um processo observar e controlar outro (usada por depuradores e pelo PRoot). |
| **PTY** | Pseudo-terminal; par mestre/escravo que emula um terminal físico. |
| **Rootfs** | Sistema de arquivos raiz de uma distribuição. |
| **SELinux** | Controle de acesso obrigatório usado pelo Android para restringir aplicativos. |
| **Socket.IO** | Biblioteca de comunicação em tempo real sobre WebSocket com *fallback* para *long polling*. |
| **Supervisor** | Sistema de controle de processos que inicia, monitora e reinicia programas. |
| **Termux** | Emulador de terminal e ambiente Linux para Android que funciona sem *root*. |
| **VPS** | *Virtual Private Server*; servidor virtual alugado de um provedor. Neste trabalho, "servidor virtual privado" designa o modelo de serviço oferecido por cada Worker (ambiente Linux próprio, administrado remotamente), sem virtualização de *hardware* (ver 1.1). |
| **WebSocket** | Protocolo de comunicação bidirecional e persistente sobre TCP (RFC 6455). |
| **Worker** | Ambiente Linux criado com `proot-distro` dentro de um Node. |
| **xterm.js** | Biblioteca JavaScript que desenha um terminal no navegador. |
