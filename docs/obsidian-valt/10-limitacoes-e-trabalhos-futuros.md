# 10. Limitações, Ameaças à Validade e Trabalhos Futuros

## 10.1 Limitações do protótipo

- **Isolamento fraco:** o PRoot isola apenas a visão do sistema de arquivos. Workers compartilham rede, processos e recursos com o Termux e entre si; um Worker pode esgotar a CPU ou a memória do aparelho. Não é adequado a cargas de terceiros não confiáveis.
- **Sem limites de CPU e memória:** sem *cgroups*, o único controle disponível é o `ulimit` (arquivos abertos e número de processos).
- **Sobrecarga do `ptrace`:** cargas intensivas em chamadas de sistema (E/S, instalação de pacotes) ficam mais lentas.
- **Métricas de CPU indisponíveis sem *root*:** no Android 16 (aparelho de testes Xiaomi 2311DRK48G), o SELinux bloqueia `/proc/stat` para aplicativos, e o `top` do sistema também não consegue calcular o uso global — exibe 100% ocioso com todos os campos zerados. O agente reporta a CPU do aparelho como indisponível e passou a medir a CPU dos processos do próprio Termux (agente e Workers) por `/proc/<pid>/stat` (ver 8.5). Essa métrica não enxerga outros aplicativos: uma carga alheia ao DroidServer reduz o desempenho dos Workers sem aparecer no painel. Também não foi possível ler temperatura nem bateria; para o experimento E9 será preciso o app Termux:API ou um medidor USB externo.
- **Políticas do Android:** Doze, `lmkd` e *phantom process killer* podem encerrar o agente ou os Workers; as mitigações exigem configuração manual (e, para o *phantom process killer*, ADB ou opções de desenvolvedor).
- **Segurança:** o painel não tem autenticação; o token dos Nodes trafega sem TLS; o servidor roda com `debug=True` e `cors_allowed_origins="*"`; os eventos de terminal são difundidos a todos os clientes conectados. O protótipo deve ficar restrito a uma rede confiável.
- **Identidade por IP:** o Node é identificado pelo endereço IP; mudanças de DHCP geram registros duplicados e dois Nodes atrás do mesmo NAT colidiriam.
- **Estado volátil e ponto único de falha:** o Host guarda tudo em memória e não é replicado.
- **Sem escalonamento:** o administrador escolhe manualmente em qual Node cada Worker roda.
- **Serviços não expostos:** não há mapeamento de portas nem *proxy* reverso para acessar, a partir do Host, os serviços que rodam nos Workers.

## 10.2 Ameaças à validade

- **Validade interna:** variações de sinal Wi-Fi, temperatura ambiente e processos de outros aplicativos podem afetar as medições; controle-as (mesma sala, modo avião + Wi-Fi, aparelhos restaurados de fábrica).
- **Validade externa:** poucos modelos de aparelho e versões do Android; fabricantes (Samsung, Xiaomi, Motorola) aplicam políticas de bateria próprias e mais agressivas.
- **Validade de construto:** o uso de CPU lido via `/proc/stat` é do aparelho inteiro, não do Worker; deixe isso explícito ao interpretar os números.
- **Confiabilidade:** publique os *scripts* de *benchmark* e os dados brutos no repositório para permitir a replicação.

## 10.3 Trabalhos futuros

1. Autenticação no painel, TLS e salas (*rooms*) por sessão no Socket.IO.
2. Identificador estável por Node (UUID gerado no `setup.sh`) em vez do IP.
3. Persistência do estado do Host (SQLite) e reconciliação de estado desejado × real, ao estilo Kubernetes.
4. Escalonador automático que escolha o Node com base em CPU, memória, temperatura e nível de bateria.
5. *Proxy* reverso no Host para expor os serviços dos Workers (ex.: `http://host/w/<node>/<alias>/`).
6. Imagens de Worker pré-configuradas (*templates*) e implantação de aplicações a partir de um repositório Git.
7. Comparação com contêineres reais em aparelhos com *root* (LXC, Docker com *kernel* compatível) e com *clusters* de Raspberry Pi.
8. Gestão de bateria: limite de carga (quando o aparelho permitir) ou alimentação direta sem bateria.
9. Cálculo da intensidade de carbono (CCI) do *cluster*, comparando com uma VPS equivalente (SWITZER et al., 2023).
