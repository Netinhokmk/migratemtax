import json
import os
import shutil

import ponte
from pyodide.ffi import to_js

import migrar

BLOCO = 1024 * 1024
LIMITE = 64 * 1024
MARCA = b"\0MTAXBLB"
MANTER = migrar.EXT_TEXTO + (".luac", ".map", ".zip")


def gravar_stream(origem, destino):
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    inicio = origem.read(LIMITE)
    if len(inicio) < LIMITE or destino.lower().endswith(MANTER):
        with open(destino, "wb") as out:
            out.write(inicio)
            shutil.copyfileobj(origem, out, BLOCO)
        return
    posicao = None
    tamanho = 0
    bloco = inicio
    while bloco:
        escrito = ponte.escrever(to_js(bloco))
        posicao = escrito if posicao is None else posicao
        tamanho += len(bloco)
        bloco = origem.read(BLOCO)
    with open(destino, "wb") as out:
        out.write(inicio[:16] + MARCA + posicao.to_bytes(8, "little") + tamanho.to_bytes(8, "little"))


def buscar_texto(url):
    return ponte.buscar(url)


migrar.gravar_stream = gravar_stream
migrar.buscar_texto = buscar_texto
migrar.log = ponte.log
migrar.AO_RELATORIO = lambda dados: ponte.relatorio(json.dumps(dados, ensure_ascii=False))
migrar.CHECAR_SINTAXE = False
migrar.main()
