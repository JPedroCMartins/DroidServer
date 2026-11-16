# Resumo

> [!note] Rascunho
> Os trechos marcados com `[RESULTADO]` só podem ser preenchidos depois de executar o protocolo da nota [09 — Avaliação experimental](09-avaliacao-experimental.md). Não publique números que não foram medidos.

O crescimento do lixo eletrônico — 62 milhões de toneladas geradas em 2022, das quais apenas 22,3% foram formalmente coletadas e recicladas (BALDÉ et al., 2024) — contrasta com a capacidade computacional ociosa de smartphones descartados por falhas periféricas. Este trabalho apresenta o **DroidServer**, uma arquitetura de orquestração que transforma smartphones Android sem acesso *root* em nós de um pequeno cluster de borda. Cada nó executa, no emulador de terminal Termux, um agente em Python que provisiona ambientes Linux isolados (Alpine, Debian e Arch Linux) por meio do `proot-distro`, mantém esses ambientes como serviços com o Supervisor e sincroniza seu estado com um servidor central (Flask) por *polling* HTTP. O acesso interativo à linha de comando dos ambientes é oferecido no navegador por meio de WebSockets (Socket.IO), pseudo-terminais (PTY) e xterm.js. A avaliação, conduzida com `[RESULTADO: N]` aparelhos em uma rede local, mediu a latência de provisionamento, a latência do terminal remoto, a sobrecarga do PRoot e a estabilidade dos nós ao longo de `[RESULTADO: horas]` horas. Os resultados indicam que `[RESULTADO]`. Conclui-se que smartphones reaproveitados são viáveis para cargas leves (microsserviços, bots e automações), desde que se mitiguem as políticas de economia de energia do Android e as limitações de isolamento do PRoot.

**Palavras-chave:** computação de borda; TI verde; Android; PRoot; orquestração de clusters.

---

# Abstract

The growth of electronic waste — 62 million tonnes generated in 2022, of which only 22.3% was formally collected and recycled (BALDÉ et al., 2024) — contrasts with the idle computing capacity of smartphones discarded due to peripheral failures. This work presents **DroidServer**, an orchestration architecture that turns non-rooted Android smartphones into nodes of a small edge cluster. Each node runs, inside the Termux terminal emulator, a Python agent that provisions isolated Linux environments (Alpine, Debian and Arch Linux) through `proot-distro`, keeps them alive as Supervisor services and synchronizes its state with a central Flask server via HTTP polling. Interactive command-line access to the environments is provided in the browser through WebSockets (Socket.IO), pseudo-terminals (PTY) and xterm.js. The evaluation, carried out with `[RESULT: N]` devices on a local network, measured provisioning latency, remote terminal latency, PRoot overhead and node stability over `[RESULT: hours]` hours. Results show that `[RESULT]`. We conclude that repurposed smartphones are viable for lightweight workloads (microservices, bots and automation), provided that Android power-saving policies and PRoot isolation limits are mitigated.

**Keywords:** edge computing; green IT; Android; PRoot; cluster orchestration.
