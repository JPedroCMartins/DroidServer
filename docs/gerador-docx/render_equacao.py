"""Renderiza uma equação LaTeX em PNG (300 dpi) com o mathtext do matplotlib.

Usado pelo gerar.mjs para que a equação apareça em qualquer editor de .docx
(o WordCraft, por exemplo, ainda não tem editor de equações).

  uv run --with matplotlib python render_equacao.py '<latex>' saida.png
"""

import re
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

latex, saida = sys.argv[1], sys.argv[2]
# mathtext usa \mathrm no lugar de \text
latex = re.sub(r"\\text\{", r"\\mathrm{", latex)

plt.rcParams.update({"mathtext.fontset": "stix", "font.family": "STIXGeneral"})
fig = plt.figure(figsize=(0.01, 0.01))
fig.text(0, 0, f"${latex}$", fontsize=16)
fig.savefig(saida, dpi=300, bbox_inches="tight", pad_inches=0.04, transparent=False, facecolor="white")
