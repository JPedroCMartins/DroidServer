# 10. Limitações, Ameaças à Validade e Trabalhos Futuros

## 10.1 Limitações do protótipo

- **Isolamento fraco:** o PRoot isola só o sistema de arquivos. Os Workers compartilham rede, processos, CPU e memória entre si e com o Termux, e sem *cgroups* o único limite é o `ulimit`. Um Worker pode esgotar o aparelho, o que torna o sistema inadequado para cargas de terceiros não confiáveis. Por isso, "servidor virtual privado" vale como modelo de serviço, e não como garantia de isolamento.
- **Custo do `ptrace`:** operações de arquivo ficam até 13× mais lentas, e uma API entrega 40% a 45% da vazão nativa (E3 e E8).
- **Restrições do Android sem *root*:** o SELinux bloqueia a CPU global, a temperatura e a bateria. A CPU medida cobre só os processos do Termux, e a E9 não foi feita. O *Doze*, o `lmkd` e o *phantom process killer* podem encerrar o agente, e as mitigações exigem configuração manual.
- **Segurança:** não há TLS, então senha e *tokens* trafegam em claro, e um Node ainda não pareado aceita pareamento de qualquer máquina da rede local.
- **Gerenciamento centralizado e manual:** o Host não é replicado. Sem ele, os serviços continuam rodando, mas não se cria nem remove Workers. Também não há escalonamento automático nem *proxy* reverso para expor os serviços.
- **Distribuições:** só Alpine e Debian, que têm imagens oficiais para ARM64.

## 10.2 Ameaças à validade

A **validade interna** é afetada pelas variações do Wi-Fi e pelos processos de outros aplicativos, que a métrica de CPU não enxerga. A **validade externa** é limitada: foram só dois aparelhos, e cada fabricante tem políticas de bateria próprias. A comparação com o Android em configuração padrão, prevista para a E7, não foi feita. Para permitir a replicação, os *scripts* e os dados brutos estão no repositório.

## 10.3 Trabalhos futuros

1. TLS no painel e entre Host e Nodes, e um código de confirmação no celular durante o pareamento.
2. Escalonador automático que escolha o Node pela CPU, memória, temperatura e bateria, e *proxy* reverso no Host para expor os serviços.
3. Integração com CI/CD: atualizar e reiniciar o serviço de um Worker a cada *push* em um repositório Git.
4. Comparação com contêineres reais em aparelhos com *root* e com *clusters* de Raspberry Pi.
5. Medição de energia com um medidor USB externo e cálculo da intensidade de carbono (CCI) do *cluster* em comparação com uma VPS equivalente (SWITZER et al., 2023).
