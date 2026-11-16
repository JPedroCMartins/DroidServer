# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib>=3.8"]
# ///
"""Gera as figuras do capítulo 9.5 a partir dos CSVs de bench/resultados/.

Para cada experimento usa o CSV mais recente (ou os indicados por padrão de
nome). As figuras vão para bench/graficos/ em PNG (300 dpi, para o documento
ABNT) e SVG.

Uso:
  uv run bench/graficos.py
"""

import csv
import glob
import os
import statistics

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

RAIZ = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(RAIZ, "resultados")
SAIDA = os.path.join(RAIZ, "graficos")

# Paleta de referência validada (tema claro): slots categóricos em ordem fixa
SUPERFICIE = "#fcfcfb"
TEXTO = "#0b0b0b"
TEXTO_2 = "#52514e"
GRADE = "#e4e3df"
SERIE = ["#2a78d6", "#eb6834", "#1baf7a"]
CRITICO = "#d03b3b"

plt.rcParams.update({
    "figure.facecolor": SUPERFICIE, "axes.facecolor": SUPERFICIE, "savefig.facecolor": SUPERFICIE,
    "axes.edgecolor": GRADE, "axes.labelcolor": TEXTO_2, "xtick.color": TEXTO_2, "ytick.color": TEXTO_2,
    "text.color": TEXTO, "axes.grid": True, "grid.color": GRADE, "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 10, "axes.titlesize": 11,
    "axes.titleweight": "bold", "axes.titlelocation": "left", "legend.frameon": False,
    "lines.linewidth": 2,
})


def ler(padrao):
    arquivos = sorted(glob.glob(os.path.join(RES, padrao)))
    if not arquivos:
        return None, []
    with open(arquivos[-1], encoding="utf-8") as f:
        return arquivos[-1], list(csv.DictReader(f))


def salvar(fig, nome):
    os.makedirs(SAIDA, exist_ok=True)
    for ext in ("png", "svg"):
        fig.savefig(os.path.join(SAIDA, f"{nome}.{ext}"), dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"  {nome}.png/.svg")


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
def fig_e4():
    series = [("5 GHz, long-polling (antes da correção)", "e4_latencia_terminal_5ghz_polling_*.csv"),
              ("5 GHz, WebSocket", "e4_latencia_terminal_5ghz_websocket_*.csv"),
              ("2,4 GHz, WebSocket", "e4_latencia_terminal_24ghz_*.csv")]
    fig, ax = plt.subplots(figsize=(7, 3.6))
    desenhou = False
    for cor, (rotulo, padrao) in zip(SERIE, series):
        _, linhas = ler(padrao)
        v = sorted(x for x in (num(l["latencia_ms"]) for l in linhas) if x is not None)
        if not v:
            continue
        y = [(i + 1) / len(v) for i in range(len(v))]
        ax.step(v, y, where="post", color=cor, label=f"{rotulo} (mediana {statistics.median(v):.0f} ms)")
        desenhou = True
    if not desenhou:
        plt.close(fig)
        return
    ax.set_xscale("log")
    ax.axvline(200, color=TEXTO_2, linewidth=1, linestyle="--")
    ax.text(215, 0.5, "critério:\np95 ≤ 200 ms", color=TEXTO_2, fontsize=8, va="center")
    ax.set_xlabel("Latência de eco (ms, escala log)")
    ax.set_ylabel("Fração das teclas")
    ax.set_title("E4 — Latência de eco do terminal (CDF)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), fontsize=8, ncol=1)
    salvar(fig, "e4_latencia_terminal_cdf")


def fig_e1():
    _, linhas = ler("e1_provisionamento_*.csv")
    linhas = [l for l in linhas if l["ok"] == "True"]
    if not linhas:
        return
    grupos = [("alpine", "com"), ("alpine", "sem"), ("debian", "com"), ("debian", "sem")]
    fig, axes = plt.subplots(1, 2, figsize=(8, 3.4), sharey=False)
    for ax, campo, titulo in ((axes[0], "instalacao_s", "No aparelho (proot-distro install)"),
                              (axes[1], "total_s", "Percebido no painel (inclui o sync)")):
        for i, (d, c) in enumerate(grupos):
            v = [num(l[campo]) for l in linhas if l["distro"] == d and l["cache"] == c and num(l[campo])]
            if not v:
                continue
            cor = SERIE[0] if c == "com" else SERIE[1]
            ax.scatter([i] * len(v), v, s=28, color=cor, edgecolor=SUPERFICIE, linewidth=1.5, zorder=3)
            ax.hlines(statistics.median(v), i - 0.25, i + 0.25, color=TEXTO, linewidth=1.5, zorder=4)
        ax.set_xticks(range(len(grupos)), [f"{d.capitalize()}\n{c} cache" for d, c in grupos], fontsize=8)
        ax.set_ylabel("segundos")
        ax.set_title(titulo, fontsize=9.5)
        ax.set_ylim(bottom=0)
    fig.suptitle("E1 — Tempo de provisionamento de um Worker (traço = mediana)", x=0.01, ha="left",
                 fontweight="bold", fontsize=11)
    fig.tight_layout()
    salvar(fig, "e1_provisionamento")


def fig_e3():
    _, linhas = ler("e3_sobrecarga_proot_*.csv")
    if not linhas:
        return
    cargas = [("cpu", "CPU (sha256)"), ("processos", "fork + exec"), ("arquivos", "1000 arquivos"),
              ("escrita", "escrita 200 MB"), ("python", "início do Python")]
    rot, val = [], []
    for c, r in cargas:
        n = [num(l["segundos"]) for l in linhas if l["carga"] == c and l["ambiente"] == "nativo"]
        p = [num(l["segundos"]) for l in linhas if l["carga"] == c and l["ambiente"] == "proot"]
        if n and p:
            mn, mp = statistics.median(n), statistics.median(p)
            rot.append(r)
            val.append(100 * (mp - mn) / mn)
    fig, ax = plt.subplots(figsize=(7, 3.2))
    barras = ax.barh(rot[::-1], val[::-1], color=SERIE[0], height=0.55, zorder=3)
    for b, v in zip(barras, val[::-1]):
        ax.text(b.get_width() + (2 if v >= 0 else -2), b.get_y() + b.get_height() / 2, f"{v:+.0f}%",
                va="center", ha="left" if v >= 0 else "right", color=TEXTO, fontsize=9)
    ax.axvline(0, color=TEXTO_2, linewidth=1)
    ax.set_xlabel("Tempo a mais dentro do Worker em relação ao Termux nativo (mediana, %)")
    ax.set_title("E3 — Sobrecarga do PRoot por tipo de carga")
    ax.grid(axis="y", visible=False)
    ax.margins(x=0.15)
    salvar(fig, "e3_sobrecarga_proot")


def fig_e8():
    _, linhas = ler("e8_vazao_*.csv")
    if not linhas:
        return
    concs = sorted({int(l["concorrencia"]) for l in linhas})
    fig, ax = plt.subplots(figsize=(7, 3.4))
    for cor, (alvo, rotulo) in zip(SERIE, (("worker", "No Worker (PRoot)"), ("nativo", "Termux nativo"))):
        med = []
        for c in concs:
            v = [num(l["req_s"]) for l in linhas if l["alvo"] == alvo and int(l["concorrencia"]) == c
                 and num(l["req_s"])]
            med.append(statistics.median(v) if v else None)
        if any(m is not None for m in med):
            ax.plot(concs, med, marker="o", markersize=8, color=cor, label=rotulo,
                    markeredgecolor=SUPERFICIE, markeredgewidth=2)
    ax.set_xscale("log")
    ax.set_xticks(concs, [str(c) for c in concs])
    ax.set_xlabel("Conexões simultâneas")
    ax.set_ylabel("Requisições por segundo (mediana)")
    ax.set_ylim(bottom=0)
    ax.set_title("E8 — Vazão da API de demonstração")
    ax.legend(loc="lower right")
    salvar(fig, "e8_vazao")


def fig_e7():
    _, linhas = ler("e7_disponibilidade_*.csv")
    if len(linhas) < 2:
        return
    t0 = float(linhas[0]["t"])
    horas = [(float(l["t"]) - t0) / 3600 for l in linhas]
    ms = [num(l["http_ms"]) for l in linhas]
    fig, ax = plt.subplots(figsize=(8, 3.2))
    ax.plot([h for h, m in zip(horas, ms) if m], [m for m in ms if m], color=SERIE[0], linewidth=1,
            label="Tempo de resposta HTTP")
    falhas = [h for h, l in zip(horas, linhas) if l["http_ok"] != "True"]
    if falhas:
        topo = max(m for m in ms if m) if any(ms) else 1
        ax.scatter(falhas, [topo] * len(falhas), marker="v", s=40, color=CRITICO, zorder=4,
                   label=f"Sem resposta ({len(falhas)})")
    pids = [(h, l["servico_pid"]) for h, l in zip(horas, linhas) if l["servico_pid"]]
    reinicios = [b[0] for a, b in zip(pids, pids[1:]) if a[1] != b[1]]
    for h in reinicios:
        ax.axvline(h, color=TEXTO_2, linewidth=1, linestyle="--")
    ok = sum(1 for l in linhas if l["http_ok"] == "True")
    ax.set_yscale("log")
    ax.set_xlabel("Horas desde o início")
    ax.set_ylabel("ms (escala log)")
    ax.set_title(f"E7 — Disponibilidade: {100 * ok / len(linhas):.2f}% em {horas[-1]:.1f} h "
                 f"({len(reinicios)} reinício(s) do serviço)")
    ax.legend(loc="upper right", fontsize=8)
    salvar(fig, "e7_disponibilidade")


if __name__ == "__main__":
    print(f"Figuras em {SAIDA}:")
    for f in (fig_e4, fig_e1, fig_e3, fig_e8, fig_e7):
        f()
