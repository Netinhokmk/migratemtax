import json
import os
import re
import shutil
import stat
import sys
import tarfile
import time
import urllib.request
import zipfile

BASE = os.path.dirname(os.path.abspath(__file__))
ENTRADA = os.path.join(BASE, "ENTRADA")
SAIDA = os.path.join(BASE, "SAIDA")
CAMADA_CACHE = os.path.join(BASE, "camada_mta.json")
CAMADA_URL = "https://raw.githubusercontent.com/mtaxsa/mtax-resources/main/resources/%5Butils%5D/mta/"

PASTA_RESOURCES = "resources"
PASTA_COMPILADOS = "[COMPILADOS]"
PASTA_HYPER = "[HYPER]"
PASTA_MODELOS = "[MODELOS-CRIPTOGRAFADOS]"
PASTA_COMPILAR = "[COMPILAR]"
PASTA_BANCOS = "databases"
EXT_BANCO = (".db", ".sqlite", ".sqlite3")
ARQUIVOS_NAO_BANCO = {"thumbs.db"}
USO_BANCO = re.compile(r"""dbConnect\s*\(\s*["']sqlite["']\s*,\s*["']([^"']+)["']""", re.IGNORECASE)
AO_RELATORIO = None
TAG_HYPER = "[hs]"
MANIFEST = "mtaxmanifest.lua"
MAP_EXTENSIONS = {"mapeditorscriptingextension_c.lua", "mapeditorscriptingextension_s.lua"}
EXTENSOES = (".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz", ".tar", ".zip")
WINDOWS = os.name == "nt"
INVALIDOS = re.compile(r'[<>:"|?*\x00-\x1f]')
RESERVADOS = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}
LUA_KEYWORDS = {
    "and", "break", "do", "else", "elseif", "end", "false", "for", "function", "goto", "if", "in",
    "local", "nil", "not", "or", "repeat", "return", "then", "true", "until", "while",
}
KNOWN_TAGS = {
    "meta", "info", "script", "file", "config", "html", "map", "export", "include", "module",
    "settings", "aclrequest", "right", "min_mta_version", "download_priority_group",
    "sync_map_element_data", "oop",
}
ENTITIES = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'", "#39": "'", "#34": '"'}


def L(p):
    p = os.path.abspath(p)
    if WINDOWS and not p.startswith("\\\\?\\"):
        if p.startswith("\\\\"):
            return "\\\\?\\UNC\\" + p[2:]
        return "\\\\?\\" + p
    return p


def log(msg=""):
    print(msg, flush=True)


def limpar_readonly(func, path, _exc):
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass


def remover(path):
    if os.path.isdir(L(path)):
        shutil.rmtree(L(path), onexc=limpar_readonly)
    elif os.path.exists(L(path)):
        os.chmod(L(path), stat.S_IWRITE)
        os.remove(L(path))


def sanitizar_segmento(seg):
    seg = INVALIDOS.sub("_", seg).rstrip(" .")
    if not seg:
        seg = "_"
    if seg.split(".")[0].lower() in RESERVADOS:
        seg = "_" + seg
    return seg


def partes_seguras(nome):
    partes = [p for p in nome.replace("\\", "/").split("/") if p not in ("", ".")]
    if any(p == ".." for p in partes):
        return None
    return partes


def nome_base(arquivo):
    baixo = arquivo.lower()
    for ext in EXTENSOES:
        if baixo.endswith(ext):
            return arquivo[: -len(ext)]
    return os.path.splitext(arquivo)[0]


def eh_compilar(nome):
    return nome.lower() == PASTA_COMPILAR.lower()


def pasta_saida(caminho):
    nome = os.path.basename(caminho)
    nome = sanitizar_segmento(nome if os.path.isdir(L(caminho)) else nome_base(nome))
    if eh_compilar(os.path.basename(os.path.dirname(caminho))):
        return os.path.join(SAIDA, PASTA_COMPILAR, nome)
    return os.path.join(SAIDA, nome)


def buscar_texto(url):
    with urllib.request.urlopen(url, timeout=20) as r:
        return r.read().decode("utf-8", errors="replace")


def ler_lista_lua(fonte, chave):
    m = re.search(chave + r"\s*=\s*\{([\s\S]*?)\}", fonte)
    if not m:
        return []
    return re.findall(r'"([^"]+)"', m.group(1))


def ler_escalar_lua(fonte, chave):
    m = re.search(chave + r'\s*=\s*"([^"]*)"', fonte)
    return m.group(1) if m else ""


def coletar_globais(fonte):
    saida = []
    linhas = re.split(r"\r?\n", fonte)
    for i, linha in enumerate(linhas):
        head = re.match(r"^([ \t]*)function[ \t]+([A-Za-z_]\w*)[ \t]*\(", linha, re.ASCII)
        if not head:
            continue
        indent, nome = head.group(1), head.group(2)
        corpo = []
        for j in range(i + 1, len(linhas)):
            if linhas[j] == indent + "end":
                break
            corpo.append(linhas[j])
        saida.append((nome, "\n".join(corpo)))
    return saida


def sincronizar_camada():
    manifesto = buscar_texto(CAMADA_URL + MANIFEST)
    nome = ler_escalar_lua(manifesto, "resource_name")
    versao = ler_escalar_lua(manifesto, "resource_version")
    lados = {
        "shared": ler_lista_lua(manifesto, "shared_files"),
        "client": ler_lista_lua(manifesto, "client_files"),
        "server": ler_lista_lua(manifesto, "server_files"),
    }
    if not nome or not lados["shared"]:
        raise ValueError("manifesto da camada invalido")
    partes = list(dict.fromkeys(lados["shared"] + lados["client"] + lados["server"]))
    acessores = {}
    globais = []
    for parte in partes:
        fonte = buscar_texto(CAMADA_URL + parte)
        for m in re.finditer(
            r"function\s+(?:[\w.]+[.:])?(\w+)\s*\([^)]*\)\s*\r?\n\s*return\s+exports\[[\"']([^\"']+)[\"']\]",
            fonte,
        ):
            acessores[m.group(1)] = m.group(2)
        for m in re.finditer(
            r"local\s+function\s+(\w+)\s*\([^)]*\)[\s\S]{0,400}?return\s+exports\[[\"']([^\"']+)[\"']\]\s*\r?\nend",
            fonte,
        ):
            acessores[m.group(1)] = m.group(2)
        globais.extend(coletar_globais(fonte))
    gui = []
    if "client/core.lua" in partes:
        core = buscar_texto(CAMADA_URL + "client/core.lua")
        tabela = re.search(r"RESERVED\s*=\s*\{([\s\S]*?)\n\}", core)
        if tabela:
            gui = re.findall(r'"(gui\w+)"', tabela.group(1))
    provedores = {}
    proprios = []
    for nome_g, corpo in globais:
        provedor = None
        direto = re.search(r"exports\[[\"']([^\"']+)[\"']\]", corpo)
        if direto:
            provedor = direto.group(1)
        else:
            for acessor, alvo in acessores.items():
                if re.search(r"\b" + re.escape(acessor) + r"\s*\(", corpo):
                    provedor = alvo
                    break
        if provedor is not None:
            provedores[nome_g] = provedor
        elif nome_g not in provedores and nome_g not in proprios:
            proprios.append(nome_g)
    proprios = [n for n in proprios if n not in provedores]
    for n in gui:
        if n not in proprios:
            proprios.append(n)
    return {
        "resource": nome,
        "version": versao,
        "shared": [f":{nome}/{p}" for p in lados["shared"]],
        "client": [f":{nome}/{p}" for p in lados["client"]],
        "server": [f":{nome}/{p}" for p in lados["server"]],
        "providers": dict(sorted(provedores.items())),
        "self": sorted(proprios),
    }


def carregar_camada():
    try:
        camada = sincronizar_camada()
        with open(CAMADA_CACHE, "w", encoding="utf-8") as f:
            json.dump(camada, f, indent=2, ensure_ascii=False)
        log(f"Camada {camada['resource']} {camada['version']} sincronizada com o GitHub.")
        return camada
    except Exception as e:
        if os.path.exists(CAMADA_CACHE):
            with open(CAMADA_CACHE, encoding="utf-8") as f:
                camada = json.load(f)
            log(f"Sem acesso ao GitHub ({e}); usando camada em cache {camada['resource']} {camada['version']}.")
            return camada
        raise SystemExit(f"Nao foi possivel obter a camada [utils]/mta: {e}")


def decode_entities(valor):
    def troca(m):
        nome = m.group(1)
        conhecido = ENTITIES.get(nome.lower())
        if conhecido is not None:
            return conhecido
        try:
            if nome[:2] in ("#x", "#X"):
                return chr(int(nome[2:], 16))
            if nome.startswith("#"):
                return chr(int(nome[1:], 10))
        except (ValueError, OverflowError):
            pass
        return m.group(0)

    return re.sub(r"&(#x?[0-9a-fA-F]+|\w+);", troca, valor)


def blank_non_markup(xml):
    def blank(m):
        return re.sub(r"[^\n]", " ", m.group(0))

    xml = re.sub(r"<!--[\s\S]*?(?:-->|\Z)", blank, xml)
    xml = re.sub(r"<!\[CDATA\[[\s\S]*?(?:\]\]>|\Z)", blank, xml)
    xml = re.sub(r"<\?[\s\S]*?(?:\?>|\Z)", blank, xml)
    xml = re.sub(r"<!DOCTYPE[^>]*>", blank, xml, flags=re.IGNORECASE)
    return xml


def parse_attrs(fonte):
    attrs = {}
    for m in re.finditer(r"([\w:.-]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s\"'<>/]+))", fonte, re.ASCII):
        valor = m.group(2) if m.group(2) is not None else m.group(3) if m.group(3) is not None else m.group(4) or ""
        attrs[m.group(1).lower()] = decode_entities(valor)
    return attrs


def scan_tags(xml):
    tags = []
    for m in re.finditer(r"<\s*(/?)\s*([\w:.-]+)((?:\"[^\"]*\"|'[^']*'|[^>\"'])*)(/?)\s*>", xml, re.ASCII):
        fechando = m.group(1) == "/"
        corpo = m.group(3)
        auto = m.group(4) == "/" or corpo.rstrip().endswith("/")
        tags.append({
            "name": m.group(2).lower(),
            "attrs": {} if fechando else parse_attrs(corpo),
            "closing": fechando,
            "self": auto,
            "end": m.end(),
        })
    return tags


def read_side(raw):
    if raw is None:
        return "server", True
    v = raw.strip().lower()
    if v in ("client", "shared", "server"):
        return v, True
    return "server", False


def read_bool(raw):
    if raw is None:
        return None
    return raw.strip().lower() in ("true", "yes", "1")


def tag_content(xml, tags, i):
    aberto = tags[i]
    if aberto["self"]:
        return ""
    for j in range(i + 1, len(tags)):
        if tags[j]["closing"] and tags[j]["name"] == aberto["name"]:
            fim = xml.rfind("<", 0, tags[j]["end"])
            return decode_entities(xml[aberto["end"]:fim]).strip()
    return ""


def parse_meta(texto):
    xml = blank_non_markup(texto)
    tags = scan_tags(xml)
    meta = {
        "info": {}, "scripts": [], "files": [], "configs": [], "htmls": [], "maps": [], "exports": [],
        "includes": [], "modules": [], "acl": [], "settings": False, "setting_values": [], "min_mta": False,
        "download_priority": False, "sync_map": False, "oop": None, "unknown": [],
        "missing_root": not any(t["name"] == "meta" and not t["closing"] for t in tags),
    }
    ordem_asset = 0
    profundidade = 0
    for i, tag in enumerate(tags):
        nome = tag["name"]
        if nome == "settings":
            if tag["closing"]:
                profundidade = max(0, profundidade - 1)
            elif not tag["self"]:
                profundidade += 1
            meta["settings"] = True
            continue
        if profundidade > 0:
            if nome == "setting" and not tag["closing"] and tag["attrs"].get("name") and "value" in tag["attrs"]:
                meta["setting_values"].append((tag["attrs"]["name"], tag["attrs"]["value"]))
            continue
        if tag["closing"]:
            continue
        a = tag["attrs"]
        if nome == "info":
            if not meta["info"]:
                meta["info"] = dict(a)
        elif nome == "script":
            if not a.get("src"):
                continue
            lado, ok = read_side(a.get("type"))
            meta["scripts"].append({"src": a["src"], "side": lado, "cache": read_bool(a.get("cache"))})
            if not ok:
                meta["unknown"].append(("script-type", a["src"], a.get("type", "")))
        elif nome == "file":
            if a.get("src"):
                meta["files"].append({"src": a["src"], "download": read_bool(a.get("download")), "order": ordem_asset, "origin": "file"})
                ordem_asset += 1
        elif nome == "config":
            if a.get("src"):
                meta["configs"].append({"src": a["src"], "side": read_side(a.get("type"))[0], "order": ordem_asset, "origin": "config"})
                ordem_asset += 1
        elif nome == "html":
            if a.get("src"):
                meta["htmls"].append({
                    "src": a["src"], "default": read_bool(a.get("default")) is True,
                    "raw": read_bool(a.get("raw")) is True, "order": ordem_asset, "origin": "html",
                })
                ordem_asset += 1
        elif nome == "map":
            if a.get("src"):
                meta["maps"].append({"src": a["src"], "dimension": a.get("dimension")})
        elif nome == "export":
            if a.get("function"):
                meta["exports"].append({
                    "name": a["function"], "side": read_side(a.get("type"))[0],
                    "http": read_bool(a.get("http")) is True, "access": a.get("access"),
                })
        elif nome == "include":
            if a.get("resource"):
                meta["includes"].append(a["resource"])
        elif nome == "module":
            if a.get("src"):
                meta["modules"].append(a["src"])
        elif nome == "right":
            if a.get("name"):
                meta["acl"].append(a["name"])
        elif nome == "min_mta_version":
            meta["min_mta"] = True
        elif nome == "download_priority_group":
            meta["download_priority"] = bool(tag_content(xml, tags, i))
        elif nome == "sync_map_element_data":
            meta["sync_map"] = bool(tag_content(xml, tags, i))
        elif nome == "oop":
            meta["oop"] = read_bool(tag_content(xml, tags, i))
        elif nome not in KNOWN_TAGS:
            meta["unknown"].append((nome, "", ""))
    return meta


def is_lua(caminho):
    return len(caminho) >= 4 and caminho[-4:].lower() == ".lua"


def is_safe_relative(caminho):
    if not caminho or caminho.startswith("/") or "\\" in caminho or ":" in caminho:
        return False
    return all(s not in ("", ".", "..") for s in caminho.split("/"))


def normalizar_caminho(src):
    out = re.sub(r"/{2,}", "/", src.strip().replace("\\", "/"))
    while out.startswith("./"):
        out = out[2:]
    out = out.lstrip("/")
    while "/./" in out:
        out = out.replace("/./", "/")
    return out


def caminho_absoluto(src):
    t = src.strip()
    return bool(re.match(r"^[A-Za-z]:[\\/]", t) or re.match(r"^[\\/]{2}", t))


def segmento_casa(padrao, nome):
    p = n = 0
    estrela = -1
    marca = 0
    while n < len(nome):
        if p < len(padrao) and padrao[p].lower() == nome[n].lower():
            p += 1
            n += 1
        elif p < len(padrao) and padrao[p] == "*":
            estrela = p
            p += 1
            marca = n
        elif estrela != -1:
            p = estrela + 1
            marca += 1
            n = marca
        else:
            return False
    while p < len(padrao) and padrao[p] == "*":
        p += 1
    return p == len(padrao)


def glob_casa(padrao, pi, caminho, ni):
    p, n = pi, ni
    while p < len(padrao):
        if padrao[p] == "**":
            return any(glob_casa(padrao, p + 1, caminho, s) for s in range(n, len(caminho) + 1))
        if n >= len(caminho) or not segmento_casa(padrao[p], caminho[n]):
            return False
        p += 1
        n += 1
    return n == len(caminho)


def quote_lua(valor):
    out = '"'
    for ch in valor:
        c = ord(ch)
        if ch == "\\":
            out += "\\\\"
        elif ch == '"':
            out += '\\"'
        elif ch == "\n":
            out += "\\n"
        elif ch == "\r":
            out += "\\r"
        elif ch == "\t":
            out += "\\t"
        elif c < 0x20 or c == 0x7F:
            out += "\\" + str(c).zfill(3)
        else:
            out += ch
    return out + '"'


def emitir_lista(chave, valores):
    return "\n".join([f"{chave} = {{"] + [f"    {quote_lua(v)}," for v in valores] + ["}"])


def emitir_manifest(m):
    blocos = []
    escalares = [(k, m[k]) for k in ("resource_name", "resource_version", "resource_author") if m[k]]
    if escalares:
        largura = max(len(k) for k, _ in escalares)
        blocos.append("\n".join(f"{k.ljust(largura)} = {quote_lua(v)}" for k, v in escalares))
    if m["resource_info"]:
        linhas = ["resource_info = {"]
        for k, v in m["resource_info"]:
            lhs = k if re.match(r"^[A-Za-z_]\w*$", k, re.ASCII) and k not in LUA_KEYWORDS else f"[{quote_lua(k)}]"
            linhas.append(f"    {lhs} = {quote_lua(v)},")
        linhas.append("}")
        blocos.append("\n".join(linhas))
    for chave in ("server_files", "client_files", "shared_files", "files", "client_configs", "map_files", "exports"):
        if m[chave]:
            blocos.append(emitir_lista(chave, m[chave]))
    if m["ui_page"]:
        blocos.append(f"ui_page = {quote_lua(m['ui_page'])}")
    return "\n\n".join(blocos) + "\n" if blocos else ""


def ler_texto(caminho):
    with open(L(caminho), "rb") as f:
        dados = f.read()
    try:
        return dados.decode("utf-8-sig")
    except UnicodeDecodeError:
        return dados.decode("cp1252", errors="replace")


def listar_arquivos(raiz):
    saida = []
    raiz_l = L(raiz)
    for atual, dirs, arquivos in os.walk(raiz_l):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        rel_dir = atual[len(raiz_l):].strip("\\/").replace("\\", "/")
        for a in arquivos:
            if a.startswith("."):
                continue
            saida.append(f"{rel_dir}/{a}" if rel_dir else a)
    return saida


def achar_na_raiz(raiz, nome):
    try:
        for e in os.listdir(L(raiz)):
            if e.lower() == nome and os.path.isfile(L(os.path.join(raiz, e))):
                return e
    except OSError:
        pass
    return None


def lua_compilado(caminho):
    try:
        with open(L(caminho), "rb") as f:
            cabeca = f.read(8)
    except OSError:
        return False
    if cabeca.startswith(b"\xef\xbb\xbf"):
        cabeca = cabeca[3:]
    return len(cabeca) > 0 and cabeca[0] in (0x1B, 0x1C)


def scripts_compilados(dir_res):
    presentes = listar_arquivos(dir_res)
    por_minusculo = {p.lower(): p for p in presentes}
    candidatos = [p for p in presentes if p.lower().endswith((".lua", ".luac"))]
    meta_nome = achar_na_raiz(dir_res, "meta.xml")
    if meta_nome:
        try:
            meta = parse_meta(ler_texto(os.path.join(dir_res, meta_nome)))
        except OSError:
            meta = {"scripts": []}
        for s in meta["scripts"]:
            real = por_minusculo.get(normalizar_caminho(s["src"]).lower())
            if real and real not in candidatos:
                candidatos.append(real)
    comp = [p for p in candidatos if p.lower().endswith(".luac") or lua_compilado(os.path.join(dir_res, p))]
    return candidatos, comp


MODELO_TOKEN = re.compile(r"(^|[._])(txd|dff|col)(?=$|[._]|s3d)")
CABECALHOS_MODELO = {
    "txd": (b"\x16\x00\x00\x00",),
    "dff": (b"\x10\x00\x00\x00", b"\x2b\x00\x00\x00"),
    "col": (b"COLL", b"COL2", b"COL3", b"COL4"),
}
FORMATOS_CRIPTO = (
    ("pcrypt", "pCrypt"),
    ("tidlemdls", "NandoCrypt"),
    ("s3d", "S3D"),
    ("mtax_", "TrustStore"),
    ("pereiramods", "PereiraMods"),
    ("rfmapper", "RF Mapper"),
)


def tipo_modelo(nome):
    baixo = nome.lower()
    if "." not in baixo:
        return None
    m = MODELO_TOKEN.search(baixo.split(".", 1)[1])
    return m.group(2) if m else None


def formato_cripto(nome, cabeca):
    baixo = nome.lower()
    for chave, rotulo in FORMATOS_CRIPTO:
        if chave in baixo:
            return rotulo
    if not cabeca or not cabeca.strip(b"\x00"):
        return "arquivo vazio/corrompido"
    return "criptografia desconhecida"


def modelos_criptografados(dir_res):
    achados = []
    for rel in listar_arquivos(dir_res):
        tipo = tipo_modelo(rel.split("/")[-1])
        if not tipo:
            continue
        try:
            with open(L(os.path.join(dir_res, rel)), "rb") as f:
                cabeca = f.read(16)
        except OSError:
            continue
        if cabeca[:4] in CABECALHOS_MODELO[tipo]:
            continue
        achados.append((rel, formato_cripto(rel.split("/")[-1], cabeca)))
    return achados


def remover_diretorios_vazios(raiz):
    for atual, dirs, arquivos in os.walk(L(raiz), topdown=False):
        if atual == L(raiz):
            continue
        try:
            if not os.listdir(atual):
                os.rmdir(atual)
        except OSError:
            pass


def uso_camada(fontes, camada):
    nomes = set(camada["providers"]) | set(camada["self"])
    achados = set()
    padrao = re.compile(r"(^|[^\w.:])([A-Za-z_]\w*)", re.ASCII)
    for fonte in fontes:
        for m in padrao.finditer(fonte):
            if m.group(2) in nomes:
                achados.add(m.group(2))
    requer = {}
    for n in achados:
        prov = camada["providers"].get(n)
        if prov:
            requer.setdefault(prov, []).append(n)
    for k in requer:
        requer[k].sort()
    return sorted(achados), dict(sorted(requer.items()))


def sem_espacos(seg):
    return re.sub(r"\s+", "", seg) or "_"


def caminho_unico(novo, ocupados):
    if novo.lower() not in ocupados:
        return novo
    base, ext = os.path.splitext(novo)
    i = 2
    while f"{base}_{i}{ext}".lower() in ocupados:
        i += 1
    return f"{base}_{i}{ext}"


def renomear_espacos(dir_res, presentes):
    ocupados = {p.lower() for p in presentes}
    mapa = {}
    segmentos = {}
    lista = []
    for rel in sorted(presentes):
        partes = rel.split("/")
        limpas = [sem_espacos(p) for p in partes]
        if limpas == partes:
            continue
        novo = caminho_unico("/".join(limpas), ocupados - {rel.lower()})
        ocupados.discard(rel.lower())
        ocupados.add(novo.lower())
        destino = os.path.join(dir_res, *novo.split("/"))
        os.makedirs(L(os.path.dirname(destino)), exist_ok=True)
        os.replace(L(os.path.join(dir_res, *partes)), L(destino))
        mapa[rel.lower()] = novo
        lista.append((rel, novo))
        for antigo, limpo in zip(partes, novo.split("/")):
            if antigo != limpo:
                segmentos[antigo] = limpo
    if mapa:
        remover_diretorios_vazios(dir_res)
    return mapa, segmentos, lista


EXT_TEXTO = (".lua", ".html", ".htm", ".css", ".js", ".json", ".xml")


def aplicar_trocas(dir_res, trocas):
    if not trocas:
        return 0
    pares = dict(trocas)
    for antigo, novo in trocas.items():
        if " " in antigo:
            pares.setdefault(antigo.replace(" ", "%20"), novo)
    ordenados = sorted(pares, key=len, reverse=True)
    padrao = re.compile(r"(?<=[\"'/(\\:])(" + "|".join(re.escape(a) for a in ordenados) + r")(?=[\"'/)\\?#])")
    total = 0
    for rel in listar_arquivos(dir_res):
        if not rel.lower().endswith(EXT_TEXTO) or rel.lower() == "meta.xml":
            continue
        caminho = os.path.join(dir_res, rel)
        if lua_compilado(caminho):
            continue
        with open(L(caminho), "rb") as f:
            dados = f.read()
        texto = dados.decode("utf-8", errors="surrogateescape")
        novo, n = padrao.subn(lambda m: pares[m.group(1)], texto)
        if n:
            with open(L(caminho), "wb") as f:
                f.write(novo.encode("utf-8", errors="surrogateescape"))
            total += n
    return total


LUA_TOKEN = re.compile(r"--|\[=*\[|[\"']")
LUA_LONGO = re.compile(r"\[(=*)\[")
ESCAPES_VALIDOS = set("abfnrtv\\\"'\r\n0123456789")


def comentar_camada(dir_res, camada):
    nome = achar_na_raiz(dir_res, MANIFEST)
    if not nome:
        return 0
    caminho = os.path.join(dir_res, nome)
    padrao = re.compile(r"""^([ \t]*)(["']:%s/)""" % re.escape(camada["resource"]), re.MULTILINE)
    texto, total = padrao.subn(r"\1-- \2", ler_texto(caminho))
    if total:
        with open(L(caminho), "w", encoding="utf-8", newline="\n") as f:
            f.write(texto)
    return total


def corrigir_escapes(texto):
    saida = []
    i = 0
    n = len(texto)
    trocas = 0
    while i < n:
        m = LUA_TOKEN.search(texto, i)
        if not m:
            saida.append(texto[i:])
            break
        saida.append(texto[i:m.start()])
        token = m.group(0)
        if token == "--":
            longo = LUA_LONGO.match(texto, m.end())
            if longo:
                fim = texto.find("]" + longo.group(1) + "]", longo.end())
                fim = n if fim == -1 else fim + len(longo.group(1)) + 2
            else:
                fim = texto.find("\n", m.end())
                fim = n if fim == -1 else fim
            saida.append(texto[m.start():fim])
            i = fim
        elif token.startswith("["):
            fim = texto.find("]" + token[1:-1] + "]", m.end())
            fim = n if fim == -1 else fim + len(token)
            saida.append(texto[m.start():fim])
            i = fim
        else:
            j = m.end()
            partes = [token]
            while j < n:
                ch = texto[j]
                if ch == "\\" and j + 1 < n:
                    prox = texto[j + 1]
                    if prox in ESCAPES_VALIDOS:
                        partes.append(texto[j:j + 2])
                    else:
                        partes.append(prox)
                        trocas += 1
                    j += 2
                    continue
                partes.append(ch)
                j += 1
                if ch == token or ch == "\n":
                    break
            saida.append("".join(partes))
            i = j
    return "".join(saida), trocas


def corrigir_escapes_resource(dir_res):
    total = 0
    arquivos = 0
    for rel in listar_arquivos(dir_res):
        if not is_lua(rel):
            continue
        caminho = os.path.join(dir_res, rel)
        if lua_compilado(caminho):
            continue
        with open(L(caminho), "rb") as f:
            dados = f.read()
        bom = dados.startswith(b"\xef\xbb\xbf")
        texto = dados[3 if bom else 0:].decode("utf-8", errors="surrogateescape")
        novo, n = corrigir_escapes(texto)
        if n or bom:
            with open(L(caminho), "wb") as f:
                f.write(novo.encode("utf-8", errors="surrogateescape"))
            total += n
            arquivos += 1
    return total, arquivos


def valor_setting(bruto):
    t = bruto.strip()
    if t.startswith("["):
        try:
            v = json.loads(t)
            return v if isinstance(v, list) else [v]
        except ValueError:
            pass
    return [bruto]


def lua_valor(v):
    if v is None:
        return "nil"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v) if v == v and v not in (float("inf"), float("-inf")) else "0"
    if isinstance(v, str):
        return quote_lua(v)
    if isinstance(v, list):
        return "{ " + ", ".join(lua_valor(x) for x in v) + " }" if v else "{}"
    if isinstance(v, dict):
        return "{ " + ", ".join(f"[{quote_lua(str(k))}] = {lua_valor(x)}" for k, x in v.items()) + " }" if v else "{}"
    return quote_lua(str(v))


def gerar_settings_lua(valores):
    linhas = ["local settings = {"]
    vistos = set()
    for nome, bruto in valores:
        chave = re.sub(r"^[*#@]", "", nome.strip())
        if not chave or chave in vistos:
            continue
        vistos.add(chave)
        itens = valor_setting(bruto)
        corpo = ", ".join(lua_valor(x) for x in itens)
        linhas.append(f"    [{quote_lua(chave)}] = {{ n = {len(itens)}{', ' + corpo if corpo else ''} }},")
    linhas += [
        "}",
        "",
        "local unpack = table.unpack or unpack",
        "",
        "local function settingKey(name)",
        "    if type(name) ~= \"string\" then",
        "        return name",
        "    end",
        "    name = (name:gsub(\"^[%*#@]\", \"\"))",
        "    if settings[name] == nil then",
        "        local dot = name:find(\".\", 1, true)",
        "        if dot then",
        "            name = (name:sub(dot + 1):gsub(\"^[%*#@]\", \"\"))",
        "        end",
        "    end",
        "    return name",
        "end",
        "",
        "function get(name)",
        "    local value = settings[settingKey(name)]",
        "    if value == nil then",
        "        return false",
        "    end",
        "    return unpack(value, 1, value.n)",
        "end",
        "",
        "function set(name, value)",
        "    settings[settingKey(name)] = { n = 1, value }",
        "    return true",
        "end",
    ]
    return "\n".join(linhas) + "\n"


try:
    from lupa.lua54 import LuaRuntime
    CHECAR_SINTAXE = LuaRuntime().eval("function(s, n) local f, e = load(s, '=' .. n) return e end")
except Exception:
    CHECAR_SINTAXE = None


USO_GET = re.compile(r"(^|[^\w.:\"'])get\s*[(\"']", re.ASCII | re.MULTILINE)
SETTINGS_LUA = "mtax_settings.lua"


def converter(dir_res, nome_pasta, camada, trocas_globais=None):
    avisos = []
    say = lambda nivel, msg: avisos.append((nivel, msg))

    meta_nome = achar_na_raiz(dir_res, "meta.xml")
    texto = ler_texto(os.path.join(dir_res, meta_nome)) if meta_nome else ""
    meta = parse_meta(texto)
    meta["files"] = [a for a in meta["files"] if not eh_banco(normalizar_caminho(a["src"]))]
    meta["configs"] = [a for a in meta["configs"] if not eh_banco(normalizar_caminho(a["src"]))]
    if meta["missing_root"]:
        say("AVISO", "meta.xml sem raiz <meta>")

    removidos_map = []
    for rel in listar_arquivos(dir_res):
        if rel.split("/")[-1].lower() in MAP_EXTENSIONS:
            remover(os.path.join(dir_res, rel))
            removidos_map.append(rel)
    if removidos_map:
        meta["scripts"] = [s for s in meta["scripts"] if normalizar_caminho(s["src"]).split("/")[-1].lower() not in MAP_EXTENSIONS]
        say("INFO", f"removidos {len(removidos_map)} mapEditorScriptingExtension")

    mapa_espacos, segmentos, lista_espacos = renomear_espacos(dir_res, listar_arquivos(dir_res))
    for antigo_rel, novo_rel in lista_espacos:
        say("INFO", f"espacos removidos: {antigo_rel} -> {novo_rel}")
    trocas = dict(trocas_globais or {})
    trocas.update(segmentos)
    n_trocas = aplicar_trocas(dir_res, trocas)
    if n_trocas:
        say("INFO", f"{n_trocas} referencia(s) no codigo atualizadas para nomes sem espaco")

    presentes = listar_arquivos(dir_res)
    presentes_set = set(presentes)
    por_minusculo = {}
    for p in presentes:
        por_minusculo.setdefault(p.lower(), []).append(p)

    info = dict(meta["info"])
    versao = info.get("version") or "1.0.0"
    autor = info.get("author", "")
    info_extra = [(k, v) for k, v in info.items() if k not in ("name", "version", "author")]
    if info.get("name") and info["name"] != nome_pasta:
        info_extra.insert(0, ("name", info["name"]))

    def resolver(src_bruto, tag):
        t = src_bruto.strip()
        if not t:
            say("ERRO", f"<{tag}> com src vazio")
            return None
        if caminho_absoluto(t):
            say("BLOQUEIO", f"<{tag}> caminho absoluto removido: {t}")
            return None
        if t.startswith(":"):
            say("BLOQUEIO", f"<{tag}> referencia outro resource, removido: {t}")
            return None
        n = normalizar_caminho(t)
        n = mapa_espacos.get(n.lower(), n)
        if not is_safe_relative(n):
            say("BLOQUEIO", f"<{tag}> caminho invalido removido: {t}")
            return None
        if "*" in n:
            return n
        if n in presentes_set:
            return n
        candidatos = por_minusculo.get(n.lower(), [])
        if len(candidatos) == 1:
            say("INFO", f"caixa corrigida: {n} -> {candidatos[0]}")
            return candidatos[0]
        if len(candidatos) > 1:
            say("ERRO", f"caixa ambigua: {n} ({', '.join(candidatos)})")
            return candidatos[0]
        say("ERRO", f"<{tag}> arquivo inexistente removido do manifest: {n}")
        return None

    scripts = {"server": [], "client": [], "shared": []}
    proprios = []
    for s in meta["scripts"]:
        r = resolver(s["src"], "script")
        if r is None:
            continue
        if r == MANIFEST:
            continue
        if not is_lua(r):
            if "*" in r or lua_compilado(os.path.join(dir_res, r)):
                say("BLOQUEIO", f"script que nao e .lua removido: {r}")
                continue
            novo = r + ".lua"
            if novo not in presentes_set:
                os.replace(L(os.path.join(dir_res, r)), L(os.path.join(dir_res, novo)))
                presentes_set.discard(r)
                presentes_set.add(novo)
                presentes[presentes.index(r)] = novo
            say("INFO", f"script sem extensao .lua renomeado: {r} -> {novo}")
            r = novo
        if r in scripts[s["side"]]:
            continue
        scripts[s["side"]].append(r)
        if r not in proprios:
            proprios.append(r)

    def contagem(p):
        return sum(p in scripts[k] for k in scripts)

    cruzados = [p for p in scripts["server"] + scripts["client"] if contagem(p) > 1]
    for p in dict.fromkeys(cruzados):
        if p not in scripts["shared"]:
            scripts["shared"].append(p)
    scripts["server"] = [p for p in scripts["server"] if p not in cruzados]
    scripts["client"] = [p for p in scripts["client"] if p not in cruzados]

    arquivos = []
    client_configs = []
    ui_page = ""
    for asset in sorted(meta["files"] + meta["configs"] + meta["htmls"], key=lambda a: a["order"]):
        r = resolver(asset["src"], asset["origin"])
        if r is None or r == MANIFEST:
            continue
        if is_lua(r):
            say("BLOQUEIO", f".lua em <{asset['origin']}> removido: {r}")
            continue
        if asset["origin"] == "config":
            if asset["side"] == "client":
                if r not in client_configs:
                    client_configs.append(r)
                continue
            say("AVISO", f"config de servidor vira download publico em files: {r}")
        if asset["origin"] == "html" and asset["default"]:
            if not ui_page:
                ui_page = r
        if r in arquivos:
            continue
        arquivos.append(r)
    arquivos = [a for a in arquivos if a not in client_configs]
    if ui_page and ui_page not in arquivos:
        arquivos.append(ui_page)

    mapas = []
    for mp in meta["maps"]:
        r = resolver(mp["src"], "map")
        if r is None:
            continue
        if is_lua(r):
            say("BLOQUEIO", f".lua em <map> removido: {r}")
            continue
        if r not in mapas:
            mapas.append(r)
        if mp["dimension"] is not None:
            say("INFO", f"dimension do mapa ignorada: {r}")

    exports = []
    for e in meta["exports"]:
        n = e["name"].strip()
        if not re.match(r"^[A-Za-z_]\w*$", n, re.ASCII):
            say("ERRO", f"export invalido removido: {n}")
            continue
        if n not in exports:
            exports.append(n)

    for inc in meta["includes"]:
        say("AVISO", f"<include> nao suportado: {inc}")
    for r in meta["acl"]:
        say("AVISO", f"<aclrequest> nao suportado: {r}")
    if meta["modules"]:
        say("AVISO", f"{len(meta['modules'])} <module> nao suportado")

    mapa_puro = bool(mapas) and not proprios and not arquivos and not client_configs
    if mapa_puro:
        manter = {m.lower() for m in mapas}
        for rel in presentes:
            if rel.lower() not in manter:
                remover(os.path.join(dir_res, rel))
        remover_diretorios_vazios(dir_res)
        say("INFO", "mapa puro: mantido apenas o .map")
    else:
        declarados = set(scripts["server"] + scripts["client"] + scripts["shared"] + arquivos + client_configs + mapas)
        soltos = sorted(p for p in presentes if is_lua(p) and p not in declarados and p != MANIFEST)
        if "migration.lua" in soltos:
            remover(os.path.join(dir_res, "migration.lua"))
            soltos.remove("migration.lua")
            say("INFO", "migration.lua antigo removido")

    n_escapes, n_arq_escapes = corrigir_escapes_resource(dir_res)
    if n_escapes:
        say("INFO", f"{n_escapes} escape(s) invalido(s) do Lua 5.1 corrigido(s) em {n_arq_escapes} arquivo(s)")

    def expandir(p):
        if "*" not in p:
            return [p]
        return [c for c in presentes if is_lua(c) and glob_casa(p.split("/"), 0, c.split("/"), 0)]

    fontes = {}
    for p in proprios:
        for real in expandir(p):
            try:
                fontes[real] = ler_texto(os.path.join(dir_res, real))
            except OSError:
                pass
    nomes_usados, requer = uso_camada(list(fontes.values()), camada)
    bancos_recusados = {m for fonte in fontes.values() for m in USO_BANCO.findall(fonte) if m != ":memory:" and (":" in m or ".." in m or m[0] in "/\\")}
    for caminho in sorted(bancos_recusados):
        say("AVISO", f"o MTAX recusa este caminho no dbConnect: {caminho}. Use um nome simples, como banco.db")
    if CHECAR_SINTAXE:
        for real, fonte in fontes.items():
            erro = CHECAR_SINTAXE(fonte.encode("utf-8", errors="replace"), real)
            if erro:
                say("ERRO", f"sintaxe Lua (o MTAX vai recusar): {erro}")

    lado_servidor = {real for p in scripts["server"] + scripts["shared"] for real in expandir(p)}
    usa_get = any(USO_GET.search(fonte) for real, fonte in fontes.items() if real in lado_servidor)
    if usa_get:
        with open(L(os.path.join(dir_res, SETTINGS_LUA)), "w", encoding="utf-8", newline="\n") as f:
            f.write(gerar_settings_lua(meta["setting_values"]))
        scripts["server"] = [SETTINGS_LUA] + [p for p in scripts["server"] if p != SETTINGS_LUA]
        say("INFO", f"get() mapeado em {SETTINGS_LUA} com {len(meta['setting_values'])} setting(s) do meta.xml")

    modelagem = (
        not scripts["server"] and not scripts["shared"]
        and set(nomes_usados) <= {"addEventHandler"}
        and any(tipo_modelo(p.split("/")[-1]) for p in presentes)
    )
    if modelagem and proprios:
        say("INFO", "modelagem: :mta nao adicionado ao manifest")
    elif proprios and nome_pasta != camada["resource"]:
        scripts["shared"] = camada["shared"] + scripts["shared"]
        scripts["client"] = camada["client"] + scripts["client"]
        scripts["server"] = camada["server"] + scripts["server"]

    manifest = {
        "resource_name": nome_pasta,
        "resource_version": versao,
        "resource_author": autor,
        "resource_info": info_extra,
        "server_files": scripts["server"],
        "client_files": scripts["client"],
        "shared_files": scripts["shared"],
        "files": arquivos,
        "client_configs": client_configs,
        "map_files": mapas,
        "exports": exports,
        "ui_page": ui_page,
    }
    with open(L(os.path.join(dir_res, MANIFEST)), "w", encoding="utf-8", newline="\n") as f:
        f.write(emitir_manifest(manifest))
    meta_final = achar_na_raiz(dir_res, "meta.xml")
    if meta_final:
        remover(os.path.join(dir_res, meta_final))
    return avisos, requer, mapa_puro


def escolher_raiz(nomes):
    contagem = {}
    for nome in nomes:
        partes = partes_seguras(nome)
        if not partes or any(p.lower() == "resource-cache" for p in partes):
            continue
        for i, p in enumerate(partes[:-1]):
            if p.lower() == PASTA_RESOURCES:
                chave = tuple(partes[: i + 1])
                if partes[-1].lower() in ("meta.xml", MANIFEST):
                    contagem[chave] = contagem.get(chave, 0) + 1
                else:
                    contagem.setdefault(chave, 0)
                break
    if not contagem:
        return ()
    return max(contagem.items(), key=lambda kv: (kv[1], -len(kv[0])))[0]


def destino_relativo(nome, raiz):
    partes = partes_seguras(nome)
    if not partes or any(p.lower() == "resource-cache" for p in partes):
        return None
    if tuple(partes[: len(raiz)]) != raiz:
        return None
    resto = partes[len(raiz):]
    if not resto:
        return None
    return [sanitizar_segmento(p) for p in resto]


def gravar_stream(origem, destino):
    os.makedirs(L(os.path.dirname(destino)), exist_ok=True)
    with open(L(destino), "wb") as out:
        shutil.copyfileobj(origem, out, 1024 * 1024)


def arquivos_da_pasta(pasta):
    base = L(pasta)
    for atual, _, arquivos in os.walk(base):
        for a in arquivos:
            yield os.path.relpath(os.path.join(atual, a), base).replace("\\", "/")


def copiar_pasta(pasta, destino):
    nomes = list(arquivos_da_pasta(pasta))
    na_raiz = {n.lower() for n in nomes if "/" not in n}
    prefixo = []
    raiz = ()
    if "meta.xml" in na_raiz or MANIFEST in na_raiz:
        prefixo = [sanitizar_segmento(os.path.basename(pasta))]
    else:
        log("  Lendo pasta do backup...")
        raiz = escolher_raiz(nomes)
        log(f"  Pasta de resources: {'/'.join(raiz) or '(raiz da pasta)'}")
    total = 0
    for nome in nomes:
        rel = destino_relativo(nome, raiz)
        if rel is None:
            continue
        with open(L(os.path.join(pasta, *nome.split("/"))), "rb") as src:
            gravar_stream(src, os.path.join(destino, *prefixo, *rel))
        total += 1
        if total % 1000 == 0:
            log(f"  {total} arquivos copiados...")
    return total


def extrair(arquivo, destino):
    if os.path.isdir(L(arquivo)):
        return copiar_pasta(arquivo, destino)
    total = 0
    baixo = arquivo.lower()
    if baixo.endswith(".zip"):
        with zipfile.ZipFile(arquivo) as z:
            infos = [i for i in z.infolist() if not i.is_dir()]
            raiz = escolher_raiz([i.filename for i in infos])
            for i in infos:
                rel = destino_relativo(i.filename, raiz)
                if rel is None:
                    continue
                with z.open(i) as src:
                    gravar_stream(src, os.path.join(destino, *rel))
                total += 1
                if total % 1000 == 0:
                    log(f"  {total} arquivos extraidos...")
        return total
    log("  Lendo indice do backup...")
    with tarfile.open(arquivo, "r|*") as t:
        nomes = [m.name for m in t if m.isfile()]
    raiz = escolher_raiz(nomes)
    log(f"  Pasta de resources: {'/'.join(raiz) or '(raiz do backup)'}")
    with tarfile.open(arquivo, "r|*") as t:
        for m in t:
            if not m.isfile():
                continue
            rel = destino_relativo(m.name, raiz)
            if rel is None:
                continue
            src = t.extractfile(m)
            if src is None:
                continue
            gravar_stream(src, os.path.join(destino, *rel))
            total += 1
            if total % 1000 == 0:
                log(f"  {total} arquivos extraidos...")
    return total


def expandir_zip_resource(caminho_zip, pasta):
    try:
        with zipfile.ZipFile(L(caminho_zip)) as z:
            infos = [i for i in z.infolist() if not i.is_dir()]
            nomes = [partes_seguras(i.filename) for i in infos]
            if any(n is None for n in nomes) or not nomes:
                return False
            prefixo = 0
            if not any(len(n) == 1 and n[0].lower() == "meta.xml" for n in nomes):
                topos = {n[0] for n in nomes}
                if len(topos) == 1 and any(len(n) == 2 and n[1].lower() == "meta.xml" for n in nomes):
                    prefixo = 1
                else:
                    return False
            for info, partes in zip(infos, nomes):
                resto = partes[prefixo:]
                if not resto:
                    continue
                with z.open(info) as src:
                    gravar_stream(src, os.path.join(pasta, *[sanitizar_segmento(p) for p in resto]))
        return True
    except (zipfile.BadZipFile, OSError):
        return False


def descobrir_resources(raiz):
    encontrados = []

    def visitar(pasta, rel):
        try:
            entradas = sorted(os.listdir(L(pasta)))
        except OSError:
            return
        arquivos_baixo = {e.lower() for e in entradas if os.path.isfile(L(os.path.join(pasta, e)))}
        if rel and ("meta.xml" in arquivos_baixo or MANIFEST in arquivos_baixo):
            encontrados.append(rel)
            return
        for e in entradas:
            caminho = os.path.join(pasta, e)
            if e.lower().endswith(".zip") and os.path.isfile(L(caminho)):
                alvo = os.path.join(pasta, sanitizar_segmento(e[:-4]))
                if os.path.exists(L(alvo)):
                    remover(caminho)
                    continue
                if expandir_zip_resource(caminho, alvo):
                    remover(caminho)
        for e in sorted(os.listdir(L(pasta))):
            caminho = os.path.join(pasta, e)
            if os.path.isdir(L(caminho)) and not e.startswith("."):
                visitar(caminho, rel + [e])

    visitar(raiz, [])
    return encontrados


def eh_banco(caminho):
    nome = caminho.lower().split("/")[-1]
    return nome.endswith(EXT_BANCO) and nome not in ARQUIVOS_NAO_BANCO


def mover_bancos(dir_res, rel_res, pasta_bancos):
    movidos, conflitos = [], []
    arquivos = [r for r in listar_arquivos(dir_res) if eh_banco(r)]
    for rel in arquivos:
        partes = rel.split("/")
        destino = os.path.join(pasta_bancos, *partes)
        if os.path.exists(L(destino)):
            destino = os.path.join(pasta_bancos, *rel_res, *partes)
            conflitos.append(f"{'/'.join(rel_res)}/{rel}")
        mover(os.path.join(dir_res, *partes), destino)
        movidos.append(os.path.relpath(destino, pasta_bancos).replace(os.sep, "/"))
    if arquivos:
        remover_diretorios_vazios(dir_res)
    return movidos, conflitos


def mover(origem, destino):
    os.makedirs(L(os.path.dirname(destino)), exist_ok=True)
    if os.path.exists(L(destino)):
        remover(destino)
    shutil.move(L(origem), L(destino))


def processar(arquivo, camada):
    saida = pasta_saida(arquivo)
    tudo_compilar = eh_compilar(os.path.basename(os.path.dirname(arquivo)))
    trabalho = os.path.join(saida, ".extraindo")
    inicio = time.time()
    log(f"\n=== {os.path.basename(arquivo)} ===")
    if os.path.exists(L(saida)):
        remover(saida)
    os.makedirs(L(trabalho), exist_ok=True)

    total = extrair(arquivo, trabalho)
    log(f"  {total} arquivos de resources extraidos.")

    resources = descobrir_resources(trabalho)
    log(f"  {len(resources)} resources encontrados.")

    nomes_ocupados = {rel[-1].lower() for rel in resources if sem_espacos(rel[-1]) == rel[-1]}
    novos = {}
    trocas_globais = {}
    renomeados = []
    for rel in resources:
        nome_novo = rel[-1]
        if sem_espacos(nome_novo) != nome_novo:
            nome_novo = caminho_unico(sem_espacos(nome_novo), nomes_ocupados)
            nomes_ocupados.add(nome_novo.lower())
            trocas_globais[rel[-1]] = nome_novo
        novo_rel = [sem_espacos(p) for p in rel[:-1]] + [nome_novo]
        novos[tuple(rel)] = novo_rel
        if novo_rel != rel:
            renomeados.append(("/".join(rel), "/".join(novo_rel)))

    hyper, compilados, convertidos, ja_migrados, mapas, modelos = [], [], [], [], [], []
    comentados = []
    bancos, bancos_conflito = [], []
    for rel in resources:
        origem = os.path.join(trabalho, *rel)
        novo_rel = novos[tuple(rel)]
        rel_txt = "/".join(novo_rel)
        comentar = tudo_compilar or any(eh_compilar(p) for p in rel)
        movidos, conflitos = mover_bancos(origem, novo_rel, os.path.join(saida, PASTA_BANCOS))
        bancos += movidos
        bancos_conflito += conflitos
        nome_res = novo_rel[-1]
        if TAG_HYPER in nome_res.lower():
            mover(origem, os.path.join(saida, PASTA_HYPER, *novo_rel))
            hyper.append(rel_txt)
            continue
        luas, comp = scripts_compilados(origem)
        cripto = modelos_criptografados(origem)
        if cripto:
            mover(origem, os.path.join(saida, PASTA_MODELOS, *novo_rel))
            modelos.append((rel_txt, cripto, comp))
            continue
        if comp:
            mover(origem, os.path.join(saida, PASTA_COMPILADOS, *novo_rel))
            compilados.append((rel_txt, comp, len(luas)))
            continue
        if achar_na_raiz(origem, MANIFEST):
            meta_velho = achar_na_raiz(origem, "meta.xml")
            if meta_velho:
                remover(os.path.join(origem, meta_velho))
            if comentar and comentar_camada(origem, camada):
                comentados.append(rel_txt)
            mover(origem, os.path.join(saida, PASTA_RESOURCES, *novo_rel))
            ja_migrados.append(rel_txt)
            continue
        try:
            avisos, requer, mapa_puro = converter(origem, nome_res, camada, trocas_globais)
        except Exception as e:
            avisos, requer, mapa_puro = [("ERRO", f"falha na conversao: {e}")], {}, False
        if comentar and comentar_camada(origem, camada):
            comentados.append(rel_txt)
        mover(origem, os.path.join(saida, PASTA_RESOURCES, *novo_rel))
        convertidos.append((rel_txt, avisos))
        if mapa_puro:
            mapas.append(rel_txt)

    remover(trabalho)

    linhas = [
        f"Backup: {os.path.basename(arquivo)}",
        f"Data: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Camada: [utils]/{camada['resource']} {camada['version']}",
        "",
        f"Resources encontrados: {len(resources)}",
        f"Convertidos (mtaxmanifest gerado): {len(convertidos)}",
        f"  dos quais mapas puros: {len(mapas)}",
        f"Ja possuiam mtaxmanifest: {len(ja_migrados)}",
        f"Modelos criptografados ({PASTA_MODELOS}): {len(modelos)}",
        f"Compilados ({PASTA_COMPILADOS}): {len(compilados)}",
        f"Hyper Scripts ({PASTA_HYPER}): {len(hyper)}",
        f"Com :{camada['resource']} comentado ({PASTA_COMPILAR}): {len(comentados)}",
        f"Tempo: {time.time() - inicio:.1f}s",
        "",
        f"Obrigatorio no servidor MTAX: [utils]/{camada['resource']} iniciado.",
    ]
    if bancos:
        linhas += ["", f"=== BANCOS MOVIDOS PARA {PASTA_BANCOS} ({len(bancos)}) ===", f"  Copie a pasta {PASTA_BANCOS} para a pasta do servidor MTAX, junto do server.cfg."]
        linhas += [f"  {b}" for b in bancos]
    if bancos_conflito:
        linhas += ["", "=== BANCOS COM NOME REPETIDO ===", "  Ficaram em uma subpasta para nao sobrescrever. Ajuste o dbConnect destes sistemas para o novo caminho."]
        linhas += [f"  {b}" for b in bancos_conflito]
    if renomeados:
        linhas += ["", f"=== ESPACOS REMOVIDOS DOS NOMES ({len(renomeados)}) ==="]
        linhas += [f"  {a}  ->  {b}" for a, b in renomeados]
    if modelos:
        linhas += ["", f"=== {PASTA_MODELOS} ===", "  Entre em contato com a loja responsavel. Se foi encomenda, peca os modelos sem criptografia."]
        for rel_txt, cripto, comp in modelos:
            formatos = sorted({f for _, f in cripto})
            extra = f", {len(comp)} script(s) compilado(s)" if comp else ""
            linhas.append(f"  {rel_txt} ({len(cripto)} modelo(s): {', '.join(formatos)}{extra})")
            for arq, fmt in cripto[:10]:
                linhas.append(f"      {arq}  [{fmt}]")
            if len(cripto) > 10:
                linhas.append(f"      ... +{len(cripto) - 10}")
    if hyper:
        linhas += ["", f"=== {PASTA_HYPER} ==="] + [f"  {h}" for h in hyper]
    if compilados:
        linhas += ["", f"=== {PASTA_COMPILADOS} ===", "  Entre em contato com a loja responsavel para que migre o sistema para o MTAX."]
        for rel_txt, comp, total_lua in compilados:
            linhas.append(f"  {rel_txt} ({len(comp)}/{total_lua} scripts compilados)")
            for c in comp[:10]:
                linhas.append(f"      {c}")
            if len(comp) > 10:
                linhas.append(f"      ... +{len(comp) - 10}")
    if ja_migrados:
        linhas += ["", "=== JA POSSUIAM MTAXMANIFEST ==="] + [f"  {r}" for r in ja_migrados]
    linhas += ["", "=== CONVERTIDOS ==="]
    ordem = {"BLOQUEIO": 0, "ERRO": 1, "AVISO": 2, "INFO": 3}
    for rel_txt, avisos in convertidos:
        linhas.append(f"  {rel_txt}")
        for nivel, msg in sorted(avisos, key=lambda a: ordem[a[0]]):
            linhas.append(f"      [{nivel}] {msg}")
    with open(L(os.path.join(saida, "relatorio.txt")), "w", encoding="utf-8") as f:
        f.write("\n".join(linhas) + "\n")

    if AO_RELATORIO:
        AO_RELATORIO({
            "nome": os.path.relpath(saida, SAIDA).replace(os.sep, "/"),
            "convertidos": [{"resource": r, "avisos": [{"nivel": n, "msg": m} for n, m in a]} for r, a in convertidos],
            "ja_migrados": ja_migrados,
            "mapas": mapas,
            "comentados": comentados,
            "bancos": bancos,
            "bancos_conflito": bancos_conflito,
            "compilados": [{"resource": r, "arquivos": c, "total": t} for r, c, t in compilados],
            "modelos": [{"resource": r, "arquivos": [f"{a} ({f})" for a, f in cr], "compilados": len(co)} for r, cr, co in modelos],
            "hyper": hyper,
        })

    log(f"  Convertidos: {len(convertidos)} | Mapas puros: {len(mapas)} | Ja migrados: {len(ja_migrados)} | Modelos criptografados: {len(modelos)} | Compilados: {len(compilados)} | Hyper: {len(hyper)}")
    log(f"  Saida: {saida}")
    log(f"  Relatorio: {os.path.join(saida, 'relatorio.txt')}")


def pendentes(forcar):
    lista = []
    itens = []
    for e in sorted(os.listdir(ENTRADA)):
        caminho = os.path.join(ENTRADA, e)
        if eh_compilar(e) and os.path.isdir(caminho):
            itens += [os.path.join(caminho, x) for x in sorted(os.listdir(caminho))]
        else:
            itens.append(caminho)
    for caminho in itens:
        e = os.path.basename(caminho)
        eh_pasta = os.path.isdir(caminho) and not e.startswith(".")
        if not eh_pasta and not (os.path.isfile(caminho) and e.lower().endswith(EXTENSOES)):
            continue
        if not forcar and os.path.exists(L(os.path.join(pasta_saida(caminho), "relatorio.txt"))):
            continue
        if eh_pasta and next(arquivos_da_pasta(caminho), None) is None:
            continue
        lista.append(caminho)
    return lista


def assinatura(pasta):
    tamanhos = [os.path.getsize(L(os.path.join(pasta, *n.split("/")))) for n in arquivos_da_pasta(pasta)]
    return len(tamanhos), sum(tamanhos)


def arquivo_estavel(caminho):
    try:
        if os.path.isdir(caminho):
            antes = assinatura(caminho)
            time.sleep(3)
            return antes[0] > 0 and assinatura(caminho) == antes
        antes = os.path.getsize(caminho)
        time.sleep(3)
        if os.path.getsize(caminho) != antes:
            return False
        with open(caminho, "rb"):
            return True
    except OSError:
        return False


def main():
    forcar = "--forcar" in sys.argv
    observar = "--watch" in sys.argv
    os.makedirs(ENTRADA, exist_ok=True)
    os.makedirs(SAIDA, exist_ok=True)
    camada = carregar_camada()
    if CHECAR_SINTAXE is None:
        log("Checagem de sintaxe Lua desativada (instale com: pip install lupa).")
    feitos = set()
    while True:
        for arquivo in pendentes(forcar):
            if arquivo in feitos:
                continue
            if observar and not arquivo_estavel(arquivo):
                continue
            try:
                processar(arquivo, camada)
            except Exception as e:
                log(f"  FALHA em {os.path.basename(arquivo)}: {e}")
            feitos.add(arquivo)
        if not observar:
            break
        time.sleep(10)
    if not feitos:
        log("Nenhum backup novo em ENTRADA.")


if __name__ == "__main__":
    main()
