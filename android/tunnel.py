"""Tunnel da Cloudflare (cloudflared) rodando no Termux, fora do proot.

É um "Worker" especial, um por Node: um programa do Supervisor com o nome
fixo `tunnel`, sem container. O usuário cola no painel o token do tunnel
(o mesmo do `cloudflared tunnel run --token <token>`) e o agente:

- instala o cloudflared com `pkg install`, se faltar;
- grava o token em ~/.config/droidserver/tunnel.env (0600);
- registra o programa no Supervisor, que o mantém de pé e grava o log.

O token não vai na linha de comando: o cloudflared o lê da variável
TUNNEL_TOKEN, carregada do tunnel.env. Assim ele não aparece no `ps` nem no
.conf, e o agente só devolve ao painel os últimos 4 caracteres.

Iniciar, parar, reiniciar, autostart/autorestart e os logs ao vivo usam o
mesmo caminho dos Workers (servico.executar e servico.LogsAoVivo).
"""

import logging
import os
import re
import shutil
import subprocess

import servico

log = logging.getLogger("node.tunnel")

NOME = servico.TUNNEL
# Token do Cloudflare Tunnel: base64 de um JSON (conta, tunnel e segredo)
TOKEN_RE = re.compile(r"^[A-Za-z0-9+/=_-]{40,4096}$")
INSTALAR_TIMEOUT = 600
ACOES = {"iniciar", "parar", "reiniciar", "configurar"}

_versao_cache = {}


def arquivo_env():
    return os.getenv("DROID_TUNNEL_ENV") or os.path.join(
        os.path.expanduser("~"), ".config", "droidserver", "tunnel.env")


def token_valido(token):
    return isinstance(token, str) and bool(TOKEN_RE.fullmatch(token))


def instalado():
    return shutil.which("cloudflared") is not None


def versao():
    """`cloudflared --version` (em cache pelo caminho do binário)."""
    binario = shutil.which("cloudflared")
    if not binario:
        return None
    if binario not in _versao_cache:
        try:
            proc = subprocess.run([binario, "--version"], capture_output=True, text=True, timeout=10)
            m = re.search(r"version (\S+)", proc.stdout or proc.stderr or "")
            _versao_cache[binario] = m.group(1) if m else None
        except (OSError, subprocess.SubprocessError):
            return None
    return _versao_cache[binario]


def instalar():
    """`pkg install -y cloudflared`. Devolve (ok, mensagem)."""
    log.info("[Tunnel] Instalando o cloudflared...")
    try:
        proc = subprocess.run(["pkg", "install", "-y", "cloudflared"], capture_output=True, text=True,
                              timeout=INSTALAR_TIMEOUT, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return False, "Tempo esgotado ao instalar o cloudflared."
    except OSError as e:
        return False, f"Não foi possível rodar o pkg: {e}"
    _versao_cache.clear()
    if proc.returncode != 0 or not instalado():
        erro = ((proc.stderr or "") + (proc.stdout or "")).strip()[-300:]
        return False, f"Falha ao instalar o cloudflared: {erro}"
    return True, "cloudflared instalado."


def ler_token():
    try:
        with open(arquivo_env()) as f:
            m = re.search(r"^TUNNEL_TOKEN='?([^'\n]*)'?$", f.read(), re.M)
        return m.group(1) if m else None
    except OSError:
        return None


def token_fim():
    """Últimos 4 caracteres do token: a única parte dele que sai do agente."""
    token = ler_token()
    return token[-4:] if token else None


def gravar_token(token):
    servico._gravar_atomico(arquivo_env(), f"TUNNEL_TOKEN='{token}'\n", 0o600)


def conteudo_conf(autostart=True, autorestart=True):
    return "\n".join([
        f"[program:{NOME}]",
        servico.CONF_VERSAO,
        # set -a: as variáveis do tunnel.env são exportadas para o cloudflared
        f"command=sh -c 'set -a; . \"{arquivo_env()}\"; exec cloudflared tunnel --no-autoupdate run'",
        f"autostart={'true' if autostart else 'false'}",
        f"autorestart={'true' if autorestart else 'false'}",
        "startsecs=5",
        "startretries=5",
        "stopasgroup=true",
        "killasgroup=true",
        "redirect_stderr=true",
        f"stdout_logfile={servico.arquivo_log(NOME)}",
        f"stdout_logfile_maxbytes={servico.LOG_MAX_BYTES}",
        f"stdout_logfile_backups={servico.LOG_BACKUPS}",
        "",
    ])


def gravar_conf(autostart=True, autorestart=True):
    caminho = servico.arquivo_conf(NOME)
    os.makedirs(os.path.dirname(servico.arquivo_log(NOME)), exist_ok=True)
    servico._gravar_atomico(caminho, conteudo_conf(autostart, autorestart), 0o644)


def configurado():
    return os.path.exists(servico.arquivo_conf(NOME)) and ler_token() is not None


def configurar(token):
    """Instala (se faltar), grava o token e registra/reinicia o tunnel. Devolve (ok, msg)."""
    if not token_valido(token):
        return False, "Token do tunnel inválido."
    if not instalado():
        ok, msg = instalar()
        if not ok:
            return False, msg
    opcoes = servico.ler_opcoes(NOME) or {"autostart": True, "autorestart": True}
    rodando = servico.status_supervisor().get(NOME, {}).get("estado") in ("RUNNING", "STARTING", "BACKOFF")
    gravar_token(token)
    gravar_conf(opcoes["autostart"], opcoes["autorestart"])
    servico.supervisorctl("reread", text=True, timeout=15)
    servico.supervisorctl("update", NOME, text=True, timeout=30)
    if rodando:
        # token novo: o processo antigo ainda usa o anterior
        servico.supervisorctl("restart", NOME, text=True, timeout=30)
    else:
        servico.supervisorctl("start", NOME, text=True, timeout=30)
    log.info("[Tunnel] Configurado (token …%s).", token[-4:])
    return True, f"Tunnel configurado (token …{token[-4:]})."


def remover():
    """Para o tunnel e apaga o .conf, o token e os logs. Devolve (ok, msg)."""
    servico.supervisorctl("stop", NOME, text=True, timeout=30)
    conf = servico.arquivo_conf(NOME)
    if os.path.exists(conf):
        os.remove(conf)
    servico.supervisorctl("reread", text=True, timeout=15)
    servico.supervisorctl("update", NOME, text=True, timeout=30)
    atual = servico.arquivo_log(NOME)
    for caminho in [arquivo_env(), atual] + [f"{atual}.{n}" for n in range(1, servico.LOG_BACKUPS + 1)]:
        if os.path.exists(caminho):
            os.remove(caminho)
    log.info("[Tunnel] Removido.")
    return True, "Tunnel removido."


def estado(status=None):
    """Estado do tunnel para o painel (nunca inclui o token)."""
    status = status if status is not None else servico.status_supervisor()
    st = status.get(NOME, {})
    opcoes = servico.ler_opcoes(NOME)
    return {
        "instalado": instalado(),
        "versao": versao(),
        "configurado": configurado(),
        "token_fim": token_fim(),
        "estado": st.get("estado"),
        "pid": st.get("pid"),
        "uptime": st.get("uptime"),
        "detalhe": st.get("detalhe", ""),
        "autostart": opcoes["autostart"] if opcoes else None,
        "autorestart": opcoes["autorestart"] if opcoes else None,
    }


def sem_segredo(tarefa):
    """Cópia da tarefa sem segredos (token do tunnel, senha do banco), para logs e para o painel."""
    if not isinstance(tarefa, dict):
        return tarefa
    copia = dict(tarefa)
    for chave in ("token", "senha"):
        if chave in copia:
            copia[chave] = "…" + str(copia[chave])[-4:]
    return copia
