# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""E3 — Sobrecarga do PRoot (QP1).

Roda as MESMAS cargas no Termux nativo e dentro de um Worker (sessão
`proot-distro login --isolated`), via SSH, e compara os tempos. Use um Worker
Debian: ele tem coreutils GNU como o Termux, então a diferença medida é a do
PRoot (interceptação de chamadas de sistema com ptrace), não a de binários
diferentes (o BusyBox do Alpine é outra implementação).

Cargas:
  cpu        sha256 de 256 MB vindos de /dev/zero (CPU pura, poucas syscalls)
  processos  300 execuções de `ls /` (fork + exec)
  arquivos   cria e apaga 1000 arquivos pequenos (open/write/close/unlink)
  escrita    200 MB sequenciais com fsync (E/S de disco)
  python     20 inicializações do interpretador Python

As repetições alternam a ordem (nativo/proot) para não favorecer um lado.

Uso:
  DROID_SSH="-p 8022 192.168.1.5" uv run bench/e3_sobrecarga_proot.py --worker demo_debian --repeticoes 10
"""

import argparse
import statistics

import comum

# Cada carga imprime "nome segundos"; tudo em sh POSIX (dash no Debian, bash no Termux).
CARGAS = r'''
d=${TMPDIR:-/tmp}/droid_e3_$$; mkdir -p "$d"; cd "$d" || exit 1
t() { date +%s%N; }
med() { echo "$1 $(( ($(t) - $2) / 1000 ))"; }
s=$(t); dd if=/dev/zero bs=1M count=256 2>/dev/null | sha256sum >/dev/null; med cpu $s
s=$(t); i=0; while [ $i -lt 300 ]; do ls / >/dev/null; i=$((i+1)); done; med processos $s
s=$(t); i=0; while [ $i -lt 1000 ]; do echo x > f$i; i=$((i+1)); done; rm -f f*; med arquivos $s
s=$(t); dd if=/dev/zero of=grande bs=1M count=200 conv=fsync 2>/dev/null; rm -f grande; med escrita $s
s=$(t); i=0; while [ $i -lt 20 ]; do python3 -c pass; i=$((i+1)); done; med python $s
cd /; rm -rf "$d"
'''


def rodar(ambiente, worker):
    script = CARGAS.replace("'", "'\\''")
    if ambiente == "nativo":
        cmd = f"sh -c '{script}'"
    else:
        cmd = f"proot-distro login --isolated {worker} -- sh -c '{script}'"
    codigo, saida = comum.ssh(cmd, timeout=900)
    tempos = {}
    for linha in saida.splitlines():
        partes = linha.split()
        if len(partes) == 2 and partes[1].isdigit():
            tempos[partes[0]] = int(partes[1]) / 1e6  # microssegundos -> segundos
    return tempos


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--worker", default="demo_debian")
    ap.add_argument("--repeticoes", type=int, default=10)
    args = ap.parse_args()

    csv = comum.GravadorCSV(comum.arquivo_csv("e3_sobrecarga_proot"),
                            ["repeticao", "ambiente", "carga", "segundos", "carimbo"])
    dados = {}
    for rep in range(1, args.repeticoes + 1):
        ordem = ("nativo", "proot") if rep % 2 else ("proot", "nativo")
        for ambiente in ordem:
            tempos = rodar(ambiente, args.worker)
            for carga, seg in tempos.items():
                csv.linha(repeticao=rep, ambiente=ambiente, carga=carga, segundos=round(seg, 4),
                          carimbo=comum.carimbo())
                dados.setdefault((carga, ambiente), []).append(seg)
            print(f"[{rep}/{args.repeticoes}] {ambiente:6} " +
                  "  ".join(f"{c}={v:.2f}s" for c, v in tempos.items()), flush=True)
    csv.fechar()

    print(f"\nDados: {csv.caminho}\n")
    print(f"{'carga':10} {'nativo (mediana)':>17} {'proot (mediana)':>16} {'sobrecarga':>11}")
    for carga in ("cpu", "processos", "arquivos", "escrita", "python"):
        n, p = dados.get((carga, "nativo")), dados.get((carga, "proot"))
        if not n or not p:
            continue
        mn, mp = statistics.median(n), statistics.median(p)
        print(f"{carga:10} {mn:16.3f}s {mp:15.3f}s {100 * (mp - mn) / mn:+10.1f}%")
    for carga in ("cpu", "processos", "arquivos", "escrita", "python"):
        for amb in ("nativo", "proot"):
            if dados.get((carga, amb)):
                comum.imprimir_resumo(f"{carga:9} {amb:6}", dados[(carga, amb)], "s")


if __name__ == "__main__":
    main()
