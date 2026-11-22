"""Gerenciador de arquivos da pasta home (/root) de cada worker.

O rootfs do container pertence ao usuário do Termux, então o agente lista,
grava e apaga os arquivos diretamente, sem abrir uma sessão do proot (como
o servico.py faz com o /app/run.sh). O painel chega aqui pelo Host, que
repassa as requisições para a porta de descoberta do node (5051):

  GET  /arquivos/listar?alias=&caminho=   -> itens da pasta
  GET  /arquivos/baixar?alias=&caminho=   -> o arquivo, ou a pasta em .zip
  POST /arquivos/enviar?alias=&caminho=   -> grava o corpo no caminho
  POST /arquivos/pasta?alias=&caminho=    -> cria a pasta
  POST /arquivos/apagar?alias=&caminho=   -> apaga arquivo ou pasta inteira

Só o host pareado entra: mesmo IP do pareamento e o token no cabeçalho
X-Droid-Token. O `caminho` é sempre relativo à home; nada fora dela (nem por
"..", nem por link simbólico) é lido, gravado ou apagado.
"""

import hmac
import json
import logging
import os
import shutil
import stat
import sys
import zipfile
from urllib.parse import parse_qs, quote, urlsplit

import banco
import servico

log = logging.getLogger("node.arquivos")

HOME_REL = "root"          # proot-distro entra como root, com home em /root
MAX_ITENS = 5000           # itens devolvidos por listagem
BLOCO = 256 * 1024


class ErroArquivo(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


def home(alias):
    """Caminho real da home do worker no Termux (cria se faltar)."""
    if not servico.alias_valido(alias) or alias == servico.TUNNEL:
        raise ErroArquivo("Worker não encontrado.", 404)
    if banco.existe(alias):
        raise ErroArquivo("Worker de banco não tem pasta de arquivos: use o psql pela aba Terminal.", 400)
    raiz = servico.rootfs(alias)
    if not raiz:
        raise ErroArquivo("Worker não encontrado.", 404)
    caminho = os.path.join(raiz, HOME_REL)
    os.makedirs(caminho, exist_ok=True)
    return os.path.realpath(caminho)


def _partes(caminho):
    partes = [p for p in str(caminho or "").replace("\\", "/").split("/") if p not in ("", ".")]
    if any(p == ".." or "\0" in p for p in partes):
        raise ErroArquivo("Caminho inválido.")
    return partes


def _dentro(base, caminho):
    return caminho == base or caminho.startswith(base + os.sep)


def resolver(alias, caminho, seguir=True):
    """(home, partes, caminho absoluto) de `caminho`, relativo à home.

    seguir=False não segue um link no último componente (para apagar ou
    substituir o próprio link, e não o que ele aponta).
    """
    base = home(alias)
    partes = _partes(caminho)
    if not partes:
        return base, partes, base
    pai = os.path.realpath(os.path.join(base, *partes[:-1]))
    if not _dentro(base, pai):
        raise ErroArquivo("Caminho fora da pasta home.", 403)
    alvo = os.path.join(pai, partes[-1])
    if seguir:
        alvo = os.path.realpath(alvo)
        if not _dentro(base, alvo):
            raise ErroArquivo("O link aponta para fora da pasta home.", 403)
    return base, partes, alvo


def _item(base, entrada):
    try:
        st = entrada.stat(follow_symlinks=False)
    except OSError:
        return None
    item = {"nome": entrada.name, "tamanho": None, "modificado": int(st.st_mtime), "link": False}
    if stat.S_ISLNK(st.st_mode):
        item["link"] = True
        real = os.path.realpath(entrada.path)
        # Link que sai da home (ou quebrado) não é seguido: só dá para apagar.
        if _dentro(base, real) and os.path.exists(real):
            st = os.stat(real)
        else:
            item["tipo"] = "link"
            return item
    if stat.S_ISDIR(st.st_mode):
        item["tipo"] = "pasta"
    else:
        item["tipo"] = "arquivo"
        item["tamanho"] = st.st_size
    return item


def listar(alias, caminho=""):
    base, partes, pasta = resolver(alias, caminho)
    if not os.path.isdir(pasta):
        raise ErroArquivo("Pasta não encontrada.", 404)
    itens = []
    with os.scandir(pasta) as it:
        for entrada in it:
            item = _item(base, entrada)
            if item:
                itens.append(item)
    itens.sort(key=lambda i: (i["tipo"] != "pasta", i["nome"].lower()))
    return {"ok": True, "caminho": "/".join(partes), "home": "/" + HOME_REL,
            "itens": itens[:MAX_ITENS], "truncado": len(itens) > MAX_ITENS}


def criar_pasta(alias, caminho):
    _, partes, alvo = resolver(alias, caminho, seguir=False)
    if not partes:
        raise ErroArquivo("Informe o nome da pasta.")
    if os.path.lexists(alvo):
        raise ErroArquivo("Já existe um item com esse nome.", 409)
    os.makedirs(alvo)
    return {"ok": True}


def _rmtree(caminho):
    """shutil.rmtree que também apaga o que está sem permissão de escrita."""
    def liberar(funcao, alvo, _erro):
        try:
            os.chmod(os.path.dirname(alvo), 0o700)
            if not os.path.islink(alvo):
                os.chmod(alvo, 0o700)
        except OSError:
            pass
        funcao(alvo)

    if sys.version_info >= (3, 12):
        shutil.rmtree(caminho, onexc=liberar)
    else:  # pragma: no cover - Python antigo
        shutil.rmtree(caminho, onerror=liberar)


def apagar(alias, caminho):
    _, partes, alvo = resolver(alias, caminho, seguir=False)
    if not partes:
        raise ErroArquivo("A pasta home não pode ser apagada.", 403)
    if os.path.islink(alvo) or os.path.isfile(alvo):
        os.remove(alvo)
    elif os.path.isdir(alvo):
        _rmtree(alvo)
    elif os.path.lexists(alvo):
        os.remove(alvo)  # fifo, socket...
    else:
        raise ErroArquivo("Item não encontrado.", 404)
    return {"ok": True}


def salvar(alias, caminho, leitor, tamanho):
    """Grava `tamanho` bytes de `leitor` no caminho (cria as pastas que faltarem).

    Grava num temporário e troca no fim: um envio interrompido não deixa
    arquivo pela metade, e um link no destino é substituído, não seguido.
    """
    base, partes, alvo = resolver(alias, caminho, seguir=False)
    if not partes:
        raise ErroArquivo("Informe o nome do arquivo.")
    if tamanho < 0:
        raise ErroArquivo("Tamanho inválido.")
    pai = os.path.dirname(alvo)
    if os.path.lexists(pai) and not os.path.isdir(pai):
        raise ErroArquivo("Já existe um arquivo com o nome de uma das pastas.", 409)
    os.makedirs(pai, exist_ok=True)
    if os.path.isdir(alvo) and not os.path.islink(alvo):
        raise ErroArquivo("Já existe uma pasta com esse nome.", 409)
    try:
        st = os.statvfs(pai)
        if st.f_bavail * st.f_frsize < tamanho:
            raise ErroArquivo("Sem espaço livre no celular para este arquivo.", 507)
    except (OSError, AttributeError):
        pass
    tmp = os.path.join(pai, f".{partes[-1]}.droidserver-envio")
    try:
        with open(tmp, "wb") as f:
            faltam = tamanho
            while faltam > 0:
                bloco = leitor.read(min(BLOCO, faltam))
                if not bloco:
                    raise ErroArquivo("O envio foi interrompido.")
                f.write(bloco)
                faltam -= len(bloco)
        os.replace(tmp, alvo)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return {"ok": True}


def escrever_zip(pasta, destino, nome):
    """Escreve a pasta como .zip em `destino` (pode ser um socket, sem seek).

    Links simbólicos são pulados: poderiam apontar para fora da home.
    """
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        for raiz, dirs, arquivos in os.walk(pasta):
            dirs[:] = sorted(d for d in dirs if not os.path.islink(os.path.join(raiz, d)))
            rel = os.path.relpath(raiz, pasta)
            prefixo = nome if rel == "." else f"{nome}/{rel.replace(os.sep, '/')}"
            if not arquivos and not dirs:
                zf.writestr(prefixo + "/", b"")
            for a in sorted(arquivos):
                completo = os.path.join(raiz, a)
                if os.path.islink(completo) or not os.path.isfile(completo):
                    continue
                try:
                    zf.write(completo, f"{prefixo}/{a}")
                except OSError as e:
                    log.warning("Arquivo pulado no .zip (%s): %s", completo, e)


# ---------------------------------------------------------------------------
# HTTP (chamado pelo servidor de descoberta do node.py)
# ---------------------------------------------------------------------------

def _json(h, status, corpo):
    dados = json.dumps(corpo).encode()
    h.send_response(status)
    h.send_header("Content-Type", "application/json")
    h.send_header("Content-Length", str(len(dados)))
    h.end_headers()
    h.wfile.write(dados)


def autorizado(h, config):
    token = h.headers.get("X-Droid-Token", "")
    return bool(config.pareado and config.token and h.client_address[0] == config.host_ip
                and hmac.compare_digest(token, config.token))


def _baixar(h, alias, caminho):
    base, partes, alvo = resolver(alias, caminho)
    if os.path.isfile(alvo):
        nome = partes[-1]
        with open(alvo, "rb") as f:
            h.send_response(200)
            h.send_header("Content-Type", "application/octet-stream")
            h.send_header("Content-Length", str(os.fstat(f.fileno()).st_size))
            h.send_header("X-Droid-Nome", quote(nome))
            h.end_headers()
            shutil.copyfileobj(f, h.wfile, BLOCO)
    elif os.path.isdir(alvo):
        nome = partes[-1] if partes else f"{alias}-home"
        h.send_response(200)
        h.send_header("Content-Type", "application/zip")
        h.send_header("X-Droid-Nome", quote(nome + ".zip"))
        h.end_headers()  # sem Content-Length: o fim da conexão marca o fim do .zip
        h.close_connection = True
        escrever_zip(alvo, h.wfile, nome)
    else:
        raise ErroArquivo("Item não encontrado.", 404)


def atender(h, metodo, config):
    """Atende /arquivos/* no servidor HTTP do node."""
    if not autorizado(h, config):
        return _json(h, 403, {"ok": False, "erro": "Só o host pareado acessa os arquivos."})
    url = urlsplit(h.path)
    rota = url.path.rstrip("/")
    q = parse_qs(url.query)
    alias = (q.get("alias") or [""])[0]
    caminho = (q.get("caminho") or [""])[0]
    try:
        if metodo == "GET" and rota == "/arquivos/listar":
            return _json(h, 200, listar(alias, caminho))
        if metodo == "GET" and rota == "/arquivos/baixar":
            return _baixar(h, alias, caminho)
        if metodo == "POST" and rota == "/arquivos/enviar":
            try:
                tamanho = int(h.headers.get("Content-Length", ""))
            except ValueError:
                raise ErroArquivo("Content-Length obrigatório.", 411)
            resp = salvar(alias, caminho, h.rfile, tamanho)
            log.info("[Arquivos] %s: enviado %s (%d bytes)", alias, caminho, tamanho)
            return _json(h, 200, resp)
        if metodo == "POST" and rota == "/arquivos/pasta":
            return _json(h, 200, criar_pasta(alias, caminho))
        if metodo == "POST" and rota == "/arquivos/apagar":
            resp = apagar(alias, caminho)
            log.info("[Arquivos] %s: apagado %s", alias, caminho)
            return _json(h, 200, resp)
        return _json(h, 404, {"ok": False, "erro": "não encontrado"})
    except ErroArquivo as e:
        h.close_connection = True  # o corpo de um envio recusado não foi lido
        return _json(h, e.status, {"ok": False, "erro": str(e)})
    except OSError as e:
        log.warning("[Arquivos] %s %s %s: %s", alias, rota, caminho, e)
        h.close_connection = True
        try:
            return _json(h, 500, {"ok": False, "erro": e.strerror or str(e)})
        except OSError:
            pass  # a conexão caiu no meio de um download
