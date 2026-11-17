# 10. Limitações, Ameaças à Validade e Trabalhos Futuros

## 10.1 Limitações do protótipo

- **"Servidor virtual privado" como modelo de serviço:** cada Worker se comporta, para o usuário, como uma VPS (ambiente Linux próprio administrado remotamente), mas não há virtualização de *hardware* nem isolamento pelo *kernel* (ver 1.1); garantias de isolamento e de desempenho de uma VPS de provedor não se aplicam.
- **Isolamento fraco:** o PRoot isola apenas a visão do sistema de arquivos. Workers compartilham rede, processos e recursos com o Termux e entre si; um Worker pode esgotar a CPU ou a memória do aparelho. Não é adequado a cargas de terceiros não confiáveis.
- **Sem limites de CPU e memória:** sem *cgroups*, o único controle disponível é o `ulimit` (arquivos abertos e número de processos).
- **Sobrecarga do `ptrace`:** medida na E3 — operações de metadados de arquivo ficam ~13× mais lentas e a criação de processos ~2,7×, enquanto CPU pura (+15%) e escrita sequencial (~0%) quase não são afetadas; na E8, a mesma API entrega ~40–45% da vazão nativa sob concorrência.
- **Métricas de CPU indisponíveis sem *root*:** no Android 16 (aparelho de testes Xiaomi 2311DRK48G), o SELinux bloqueia `/proc/stat` para aplicativos, e o `top` do sistema também não consegue calcular o uso global — exibe 100% ocioso com todos os campos zerados. O agente reporta a CPU do aparelho como indisponível e passou a medir a CPU dos processos do próprio Termux (agente e Workers) por `/proc/<pid>/stat` (ver 8.5). Essa métrica não enxerga outros aplicativos: uma carga alheia ao DroidServer reduz o desempenho dos Workers sem aparecer no painel. Também não foi possível ler temperatura nem bateria; para o experimento E9 será preciso o app Termux:API ou um medidor USB externo.
- **Distribuições disponíveis:** o `proot-distro` recente baixa imagens do Docker Hub, e a imagem oficial do Arch Linux só é publicada para `amd64`. Há imagens comunitárias do Arch Linux ARM (ex.: `menci/archlinuxarm`), mas, por não serem oficiais, o protótipo oferece apenas Alpine (recomendada) e Debian.
- **Políticas do Android:** Doze, `lmkd` e *phantom process killer* podem encerrar o agente ou os Workers; as mitigações exigem configuração manual (e, para o *phantom process killer*, ADB ou opções de desenvolvedor).
- **Segurança:** a Fase 2 acrescentou senha no painel, isolamento dos terminais por sala, autenticação do WebSocket dos Nodes e bloqueio de requisições de outros sites, mas **não há TLS**: senha e tokens trafegam em claro na rede local (mitigação: proxy HTTPS).
- **Pareamento sem confirmação no aparelho:** um Node ainda não pareado aceita o pareamento de qualquer máquina da rede local; não há código de confirmação exibido no celular. Depois de pareado, só o mesmo Host pode parear de novo ou desfazer. O token trafega sem TLS.
- **Estado volátil e ponto único de falha:** o Host guarda tudo em memória e não é replicado.
- **Sem escalonamento:** o administrador escolhe manualmente em qual Node cada Worker roda.
- **Serviços não expostos:** não há mapeamento de portas nem *proxy* reverso para acessar, a partir do Host, os serviços que rodam nos Workers.
- **Temperatura e energia não medidas (E9):** sem *root*, `/sys/class/thermal` e `/sys/class/power_supply` são negados pelo Android; seria necessário o Termux:API (bateria) ou um medidor USB externo.

## 10.2 Ameaças à validade

- **Validade interna:** variações de sinal Wi-Fi, temperatura ambiente e processos de outros aplicativos podem afetar as medições; controle-as (mesma sala, modo avião + Wi-Fi, aparelhos restaurados de fábrica).
- **Validade externa:** poucos modelos de aparelho e versões do Android; fabricantes (Samsung, Xiaomi, Motorola) aplicam políticas de bateria próprias e mais agressivas.
- **Validade de construto:** o uso de CPU lido via `/proc/stat` é do aparelho inteiro, não do Worker; deixe isso explícito ao interpretar os números.
- **Confiabilidade:** publique os *scripts* de *benchmark* e os dados brutos no repositório para permitir a replicação.

## 10.3 Trabalhos futuros

1. TLS no painel e no canal Host–Node (por exemplo, um *proxy* HTTPS na frente do Host); a autenticação por senha e o isolamento dos terminais por sessão já foram implementados (seção 8.6).
2. Código de confirmação exibido no celular durante o pareamento (como no Bluetooth) e TLS entre Host e Nodes.
3. Persistência do estado do Host (SQLite) e reconciliação de estado desejado × real, ao estilo Kubernetes.
4. Escalonador automático que escolha o Node com base em CPU, memória, temperatura e nível de bateria.
5. *Proxy* reverso no Host para expor os serviços dos Workers (ex.: `http://host/w/<node>/<alias>/`).
6. **Integração de CI/CD**: associar um Worker a um repositório Git e, a cada *push* (via *webhook* do GitHub/GitLab recebido pelo Host), o Node atualizar o código em `/app`, rodar a etapa de *build* e reiniciar o serviço, com os logs da implantação no painel e segredos guardados como variáveis de ambiente do Worker (fora do `run.sh` e dos logs). Junto com isso, um assistente que gere o `/app/run.sh` a partir do tipo de aplicação e imagens de Worker pré-configuradas (*templates*).
7. Comparação com contêineres reais em aparelhos com *root* (LXC, Docker com *kernel* compatível) e com *clusters* de Raspberry Pi.
8. Gestão de bateria: limite de carga (quando o aparelho permitir) ou alimentação direta sem bateria.
9. Cálculo da intensidade de carbono (CCI) do *cluster*, comparando com uma VPS equivalente (SWITZER et al., 2023).
