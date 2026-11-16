# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""E1 — Tempo de provisionamento de um Worker (QP1), com E2 e E5 de brinde.

Para cada repetição: cria o Worker pelo painel (POST /deploy_worker), espera
ele aparecer pronto, mede o disco e o remove (POST .../delete).

Tempos registrados:
  total_s      do POST até o painel mostrar o Worker criado (o que o usuário vê;
               inclui a espera do sync, até 10 s na entrega + até 10 s no retorno)
  entrega_s    E5: do POST até o agente receber a tarefa (relógios do PC e do
               celular alinhados pelo deslocamento medido por SSH)
  instalacao_s no aparelho: "Criando" -> "criado com sucesso" (proot-distro install)
  registro_s   no aparelho: "Criando" -> serviço registrado no Supervisor
  disco_mb     E2: `du` do rootfs logo após a criação
  remocao_s    do POST de remoção até o Worker sumir do painel

"Sem cache" apaga o cache de imagens do proot-distro antes da repetição
(`proot-distro clear-cache`), forçando o download.

Uso:
  DROID_SSH="-p 8022 192.168.1.5" uv run bench/e1_provisionamento.py \\
      --distros alpine debian --repeticoes 5 --cache com sem
"""

import argparse
import random
import re
import time
from datetime import datetime

import comum

LOG_AGENTE = "~/.config/droidserver/logs/node.log"


def deslocamento_relogio():
    """Segundos a somar ao relógio do celular para chegar ao do PC."""
    t0 = time.time()
    _, saida = comum.ssh("date +%s.%N", timeout=30)
    t1 = time.time()
    return (t0 + t1) / 2 - float(saida.strip())


def eventos_do_log(alias):
    """Carimbos (epoch do celular) das etapas da criação de `alias` no log do agente."""
    _, saida = comum.ssh(f"grep -h \"'{alias}'\" {LOG_AGENTE} {LOG_AGENTE}.1 2>/dev/null", timeout=30)
    marcas = {"recebida": r"Tarefa recebida: .*'criar_worker'",
              "criando": r"\[Deploy\] Criando",
              "instalado": r"Container '.*' criado com sucesso!",
              "registrado": r"registrado no Supervisor"}
    eventos = {}
    for linha in saida.splitlines():
        m = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3})", linha)
        if not m:
            continue
        t = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f").timestamp()
        for nome, padrao in marcas.items():
            if nome not in eventos and re.search(padrao, linha):
                eventos[nome] = t
    return eventos


def esperar(condicao, limite, passo=0.5):
    fim = time.time() + limite
    while time.time() < fim:
        valor = condicao()
        if valor:
            return valor
        time.sleep(passo)
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--distros", nargs="+", default=["alpine", "debian"])
    ap.add_argument("--repeticoes", type=int, default=5)
    ap.add_argument("--cache", nargs="+", default=["com", "sem"], choices=["com", "sem"])
    ap.add_argument("--limite", type=float, default=1500, help="tempo máximo por criação (s)")
    args = ap.parse_args()

    s = comum.sessao_painel()
    ip = comum.ip_do_node(s)
    csv = comum.GravadorCSV(comum.arquivo_csv("e1_provisionamento"), [
        "distro", "cache", "repeticao", "alias", "ok", "total_s", "entrega_s", "instalacao_s",
        "registro_s", "disco_mb", "remocao_s", "mensagem", "carimbo"])
    tempos = {}

    for cache in args.cache:
        for distro in args.distros:
            for rep in range(1, args.repeticoes + 1):
                alias = f"e1_{distro}_{cache}_{rep}_{int(time.time()) % 100000}"
                if cache == "sem":
                    comum.ssh("proot-distro clear-cache >/dev/null 2>&1", timeout=120)
                desloc = deslocamento_relogio()
                # Atraso aleatório: sem ele o POST cairia sempre logo depois de um
                # sync (a remoção anterior é confirmada num sync) e a entrega
                # mediria ~10 s sempre. Com ele, a fase do ciclo de 10 s é uniforme.
                time.sleep(random.uniform(0, 10))
                print(f"[{distro}, {cache} cache, {rep}/{args.repeticoes}] criando {alias}...", flush=True)

                t0 = time.time()
                r = s.post(f"{comum.HOST_URL}/deploy_worker",
                           data={"ip": ip, "alias": alias, "imagem": distro, "isolado": "1"}, timeout=10)
                r.raise_for_status()

                def resultado():
                    n = comum.estado_node(s, ip)
                    res = [x for x in n.get("resultados", []) if x.get("alias") == alias
                           and x.get("acao") == "criar_worker"]
                    return res[-1] if res else None

                res = esperar(resultado, args.limite)
                total = time.time() - t0 if res else None
                ok = bool(res and res.get("ok"))

                ev = eventos_do_log(alias)
                entrega = ev["recebida"] + desloc - t0 if "recebida" in ev else None
                inst = ev["instalado"] - ev["criando"] if {"instalado", "criando"} <= ev.keys() else None
                regi = ev["registrado"] - ev["criando"] if {"registrado", "criando"} <= ev.keys() else None
                _, du = comum.ssh(f"du -sm $PREFIX/var/lib/proot-distro/containers/{alias} 2>/dev/null | cut -f1")
                disco = int(du.strip()) if du.strip().isdigit() else None

                remocao = None
                if res:
                    t1 = time.time()
                    s.post(f"{comum.HOST_URL}/node/{ip}/worker/{alias}/delete", timeout=10)
                    sumiu = esperar(lambda: alias not in comum.estado_node(s, ip).get("workers", []), 300)
                    remocao = time.time() - t1 if sumiu else None

                csv.linha(distro=distro, cache=cache, repeticao=rep, alias=alias, ok=ok,
                          total_s=_r(total), entrega_s=_r(entrega), instalacao_s=_r(inst),
                          registro_s=_r(regi), disco_mb=disco if disco is not None else "",
                          remocao_s=_r(remocao), mensagem=(res or {}).get("msg", "tempo esgotado"),
                          carimbo=comum.carimbo())
                print(f"    ok={ok} total={_r(total)} s, entrega={_r(entrega)} s, instalação={_r(inst)} s, "
                      f"disco={disco} MB, remoção={_r(remocao)} s", flush=True)
                if ok:
                    for chave, valor in (("total", total), ("instalacao", inst), ("entrega", entrega)):
                        tempos.setdefault((distro, cache, chave), []).append(valor)

    csv.fechar()
    print(f"\nDados: {csv.caminho}")
    for (distro, cache, chave), valores in sorted(tempos.items()):
        comum.imprimir_resumo(f"{distro:6} {cache} cache {chave:10}", valores, "s")


def _r(x):
    return "" if x is None else round(x, 2)


if __name__ == "__main__":
    main()
