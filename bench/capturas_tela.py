# /// script
# requires-python = ">=3.10"
# dependencies = ["requests", "playwright"]
# ///
"""Capturas de tela do painel para a seção 8.8 do TCC (tarefa 4.6 do plano).

Abre o painel num Chrome sem janela (o do sistema, /usr/bin/google-chrome),
faz login com DROID_PANEL_PASSWORD (se o Host exigir) e salva em
docs/obsidian-valt/figuras/:

  painel_dashboard.png      Dashboard com os Nodes e o gráfico de CPU/RAM
  painel_node.png           Página do Node: criação de Worker e cartões
  painel_servico.png        Aba Serviço do Worker (visão geral, run.sh, logs)
  painel_servico_ajuda.png  Aba Serviço com a ajuda "?" aberta
  painel_terminal.png       Terminal no navegador com htop (ou top) no Worker

Não altera nada no aparelho: só abre páginas e, no terminal, roda htop e sai.
Rode ANTES de iniciar a E7, para não interferir na medição.

Uso:
  DROID_HOST_URL=http://localhost:5000 DROID_PANEL_PASSWORD=... \\
      uv run bench/capturas_tela.py --node 192.168.1.100 --worker demo_api
"""

import argparse
import os
import time

from playwright.sync_api import sync_playwright

from comum import HOST_URL, ip_do_node, sessao_painel

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASTA = os.path.join(RAIZ, "docs", "obsidian-valt", "figuras")


def salvar(pagina, nome, pagina_inteira=False):
    caminho = os.path.join(PASTA, nome)
    pagina.screenshot(path=caminho, full_page=pagina_inteira)
    print("salvo:", os.path.relpath(caminho, RAIZ))


def abrir(pagina, caminho, espera):
    pagina.goto(f"{HOST_URL}{caminho}", wait_until="networkidle")
    time.sleep(espera)  # dá tempo ao sync (10 s) e ao gráfico em tempo real


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--node", help="IP do Node (padrão: DROID_NODE_IP ou o primeiro Online)")
    ap.add_argument("--worker", default="demo_api", help="Worker mostrado nas abas Serviço e Terminal")
    ap.add_argument("--espera", type=float, default=15, help="segundos de espera em cada página com gráfico")
    args = ap.parse_args()

    # Confere login e descobre o node pela API antes de abrir o navegador
    sessao = sessao_painel()
    ip = args.node or ip_do_node(sessao)
    os.makedirs(PASTA, exist_ok=True)

    with sync_playwright() as p:
        navegador = p.chromium.launch(channel="chrome", headless=True)
        contexto = navegador.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1.5,
                                         color_scheme="dark", locale="pt-BR")
        # Reaproveita o cookie de sessão do login feito pelo requests
        for c in sessao.cookies:
            contexto.add_cookies([{"name": c.name, "value": c.value, "url": HOST_URL}])
        pagina = contexto.new_page()

        abrir(pagina, "/", args.espera)
        salvar(pagina, "painel_dashboard.png")

        abrir(pagina, f"/node/{ip}", args.espera)
        salvar(pagina, "painel_node.png", pagina_inteira=True)

        abrir(pagina, f"/node/{ip}/worker/{args.worker}", args.espera)
        salvar(pagina, "painel_servico.png", pagina_inteira=True)

        pagina.locator("[data-ajuda]").first.click()
        pagina.wait_for_selector("#ajudaPainel:not(.hidden)")
        time.sleep(1)
        pagina.eval_on_selector("#ajudaPainel", "e => e.scrollTop = 0")  # mostra o passo a passo
        time.sleep(0.5)
        salvar(pagina, "painel_servico_ajuda.png")

        abrir(pagina, f"/node/{ip}/worker/{args.worker}/terminal", 4)
        pagina.locator(".xterm").first.click()
        pagina.keyboard.type("clear; command -v htop >/dev/null && htop || top\n", delay=20)
        time.sleep(5)
        salvar(pagina, "painel_terminal.png")
        pagina.keyboard.press("q")
        pagina.keyboard.type("exit\n", delay=20)
        time.sleep(1)

        navegador.close()


if __name__ == "__main__":
    main()
