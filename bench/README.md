# bench/ — Experimentos da avaliação (Fase 3)

Scripts que executam o protocolo da seção 6 do artigo (`docs/obsidian-valt/06-avaliacao-experimental.md`).
Cada script é autocontido (`uv run` instala as dependências declaradas no topo do arquivo), grava os
**dados brutos em CSV** em `bench/resultados/` linha a linha (uma execução interrompida não perde o que já
mediu) e imprime um resumo com média, desvio-padrão, IC 95%, mediana e percentis.

| Script | Experimento | Questão | Onde roda |
|---|---|---|---|
| `e1_provisionamento.py` | **E1** tempo de provisionamento (+ **E2** disco, **E5** entrega da tarefa) | QP1, QP2 | PC (API do painel) + SSH |
| `e3_sobrecarga_proot.py` | **E3** sobrecarga do PRoot (nativo × Worker) | QP1 | SSH no celular |
| `e4_latencia_terminal.py` | **E4** latência de eco do terminal | QP2 | PC (WebSocket do painel) |
| `e7_disponibilidade.py` | **E7** disponibilidade em 24 h (+ **E6** lacunas do agente, **E10** consumo do agente) a partir do registro gravado no celular; o PC pode ficar desligado durante a medição | QP3 / H1 | Celular (registro do agente); PC só no fim, por SSH |
| `capturas_tela.py` | Capturas do painel para a seção 8.8 (Dashboard, Node, aba Serviço, ajuda, terminal) em `docs/obsidian-valt/figuras/painel_*.png`; usa o Chrome do sistema. Rodar **antes** da E7 | — | PC |
| `e8_vazao.py` | **E8** vazão da API no Worker × nativa | QP3 | PC (`hey`) + SSH |
| `comum.py` | login no painel, SSH, CSV e estatística | — | — |

## Configuração

```bash
export DROID_HOST_URL=http://localhost:5050      # painel
export DROID_PANEL_PASSWORD='...'                 # se o Host exigir login
export DROID_SSH="-p 8022 192.168.1.5"            # E1, E3, E7 (E10) e E8
```

Pré-requisitos: Host rodando com o Node *Online*; acesso SSH ao Termux por chave; `hey` no PC (E8);
um Worker Debian com `python3` para a E3 (ex.: `demo_debian`) e a API de demonstração (`demo_api`, porta 8080)
para a E7 e a E8.

## Execução (na ordem usada no TCC)

Rode um experimento por vez: cargas simultâneas distorcem os tempos.

```bash
uv run bench/e4_latencia_terminal.py --worker demo_api --amostras 500
uv run bench/e1_provisionamento.py --distros alpine debian --repeticoes 5 --cache com sem
uv run bench/e3_sobrecarga_proot.py --worker demo_debian --repeticoes 10
uv run bench/e8_vazao.py --worker demo_api --porta 8080 --concorrencias 1 10 50 --repeticoes 5 --duracao 20
# E7: o início fica gravado no celular, que acompanha e calcula sozinho; o PC e o painel podem ser desligados
uv run bench/e7_disponibilidade.py --iniciar --worker demo_api --horas 24
uv run bench/e7_disponibilidade.py --status      # progresso (atualizado a cada 15 min no celular)
uv run bench/e7_disponibilidade.py --retomar     # se o celular reiniciar: religa o acompanhamento (o registro não para)
uv run bench/e7_disponibilidade.py               # no fim: baixa o registro e gera o CSV oficial em bench/resultados/
uv run bench/e7_disponibilidade.py --resumo bench/resultados/e7_disponibilidade_<data>.csv
```

## Notas de método

- **E1:** antes de cada criação há um atraso aleatório de 0–10 s, para a fase em relação ao sync ser uniforme (sem ele, a entrega mediria sempre ~10 s). `total_s` é o tempo percebido no painel (inclui até 10 s de entrega e até 10 s de retorno pelo sync);
  `instalacao_s` vem do log do agente (só o `proot-distro install`). A **E5** (`entrega_s`) alinha os relógios
  do PC e do celular pelo deslocamento medido por SSH a cada repetição. "Sem cache" roda
  `proot-distro clear-cache` antes da repetição.
- **E3:** as cargas usam os mesmos comandos (coreutils GNU) nos dois ambientes; a ordem nativo/PRoot alterna
  entre repetições.
- **E4:** cada amostra é uma tecla e um *backspace*; o PC hospeda o Host, então o trecho navegador–Host é
  local e a medida reflete Host ↔ Node (Wi-Fi) ↔ PTY.
- **E8:** o alvo "nativo" é o mesmo `app.py` do Worker, executado pelo Python do Termux; as versões do
  interpretador podem diferir (registrar na seção 6 do artigo).
- **Fora do escopo** (limitações): E9 (temperatura e bateria: `/sys/class/thermal` e
  `/sys/class/power_supply` retornam *Permission denied* sem root no Android 16).
