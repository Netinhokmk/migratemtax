import { loadPyodide } from "https://cdn.jsdelivr.net/pyodide/v0.28.3/full/pyodide.mjs";

const APP = "/app";
const TAM_STUB = 40;
const MARCA = [0, 77, 84, 65, 88, 66, 76, 66];
const BLOCO = 1024 * 1024;
const TABELA_CRC = Int32Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c;
});

const avisar = (msg) => postMessage(msg);

class SemEspaco extends Error {
  constructor() {
    super("sem espaco");
    this.name = "QuotaExceededError";
  }
}

function gravar(alca, bytes, at) {
  if (alca.write(bytes, { at }) !== bytes.length) throw new SemEspaco();
}

function formatarGB(b) {
  return `${(b / 1024 ** 3).toFixed(1)} GB`;
}

async function conferirEspaco(itens) {
  const { quota = 0, usage = 0 } = await navigator.storage.estimate();
  const preciso = itens.reduce((s, i) => s + i.arquivo.size, 0) * 2;
  const livre = quota - usage;
  if (quota && preciso > livre) {
    throw new Error(`Este servidor precisa de ${formatarGB(preciso)} livres, mas o navegador só tem ${formatarGB(livre)} disponíveis. Libere espaço no disco. Em aba anônima o espaço é bem menor: use uma aba normal.`);
  }
}

function crc32(crc, dados) {
  let c = crc;
  for (let i = 0; i < dados.length; i++) c = TABELA_CRC[(c ^ dados[i]) & 255] ^ (c >>> 8);
  return c;
}

function ehStub(py, caminho) {
  const dados = py.FS.readFile(caminho);
  if (!MARCA.every((b, i) => dados[16 + i] === b)) return null;
  const v = new DataView(dados.buffer, dados.byteOffset);
  return { posicao: Number(v.getBigUint64(24, true)), tamanho: Number(v.getBigUint64(32, true)) };
}

function listar(py, pasta, prefixo = "") {
  const saida = [];
  for (const nome of py.FS.readdir(pasta)) {
    if (nome === "." || nome === ".." || nome === ".extraindo") continue;
    const caminho = `${pasta}/${nome}`;
    const rel = prefixo + nome;
    const st = py.FS.stat(caminho);
    if (py.FS.isDir(st.mode)) saida.push(...listar(py, caminho, `${rel}/`));
    else saida.push({ caminho, rel, tamanho: st.size });
  }
  return saida;
}

class Zip {
  constructor(alca) {
    this.alca = alca;
    this.cursor = 0;
    this.central = [];
    this.textos = new TextEncoder();
  }

  grava(bytes) {
    gravar(this.alca, bytes, this.cursor);
    this.cursor += bytes.length;
  }

  adicionar(nome, tamanho, ler) {
    const n = this.textos.encode(nome);
    const grande = tamanho >= 0xffffffff;
    const inicio = this.cursor;
    const cab = new DataView(new ArrayBuffer(30 + n.length + (grande ? 20 : 0)));
    cab.setUint32(0, 0x04034b50, true);
    cab.setUint16(4, 45, true);
    cab.setUint16(6, 0x0800, true);
    const tam32 = grande ? 0xffffffff : tamanho;
    cab.setUint32(18, tam32, true);
    cab.setUint32(22, tam32, true);
    cab.setUint16(26, n.length, true);
    cab.setUint16(28, grande ? 20 : 0, true);
    const u8 = new Uint8Array(cab.buffer);
    u8.set(n, 30);
    if (grande) {
      const x = 30 + n.length;
      cab.setUint16(x, 1, true);
      cab.setUint16(x + 2, 16, true);
      cab.setBigUint64(x + 4, BigInt(tamanho), true);
      cab.setBigUint64(x + 12, BigInt(tamanho), true);
    }
    this.grava(u8);
    let crc = -1;
    for (const bloco of ler()) {
      crc = crc32(crc, bloco);
      this.grava(bloco);
    }
    crc = (crc ^ -1) >>> 0;
    const c = new Uint8Array(4);
    new DataView(c.buffer).setUint32(0, crc, true);
    gravar(this.alca, c, inicio + 14);
    this.central.push({ n, tamanho, inicio, crc });
  }

  fechar() {
    const inicioCD = this.cursor;
    for (const e of this.central) {
      const tamG = e.tamanho >= 0xffffffff;
      const posG = e.inicio >= 0xffffffff;
      const x = (tamG ? 16 : 0) + (posG ? 8 : 0);
      const v = new DataView(new ArrayBuffer(46 + e.n.length + (x ? 4 + x : 0)));
      v.setUint32(0, 0x02014b50, true);
      v.setUint16(4, 45, true);
      v.setUint16(6, 45, true);
      v.setUint16(8, 0x0800, true);
      v.setUint32(16, e.crc, true);
      v.setUint32(20, tamG ? 0xffffffff : e.tamanho, true);
      v.setUint32(24, tamG ? 0xffffffff : e.tamanho, true);
      v.setUint16(28, e.n.length, true);
      v.setUint16(30, x ? 4 + x : 0, true);
      v.setUint32(42, posG ? 0xffffffff : e.inicio, true);
      const u8 = new Uint8Array(v.buffer);
      u8.set(e.n, 46);
      if (x) {
        let p = 46 + e.n.length;
        v.setUint16(p, 1, true);
        v.setUint16(p + 2, x, true);
        p += 4;
        if (tamG) {
          v.setBigUint64(p, BigInt(e.tamanho), true);
          v.setBigUint64(p + 8, BigInt(e.tamanho), true);
          p += 16;
        }
        if (posG) v.setBigUint64(p, BigInt(e.inicio), true);
      }
      this.grava(u8);
    }
    const tamCD = this.cursor - inicioCD;
    const total = this.central.length;
    if (total >= 0xffff || inicioCD >= 0xffffffff || tamCD >= 0xffffffff) {
      const posicao = this.cursor;
      const z = new DataView(new ArrayBuffer(76));
      z.setUint32(0, 0x06064b50, true);
      z.setBigUint64(4, 44n, true);
      z.setUint16(12, 45, true);
      z.setUint16(14, 45, true);
      z.setBigUint64(24, BigInt(total), true);
      z.setBigUint64(32, BigInt(total), true);
      z.setBigUint64(40, BigInt(tamCD), true);
      z.setBigUint64(48, BigInt(inicioCD), true);
      z.setUint32(56, 0x07064b50, true);
      z.setBigUint64(64, BigInt(posicao), true);
      z.setUint32(72, 1, true);
      this.grava(new Uint8Array(z.buffer));
    }
    const fim = new DataView(new ArrayBuffer(22));
    fim.setUint32(0, 0x06054b50, true);
    fim.setUint16(8, Math.min(total, 0xffff), true);
    fim.setUint16(10, Math.min(total, 0xffff), true);
    fim.setUint32(12, Math.min(tamCD, 0xffffffff), true);
    fim.setUint32(16, Math.min(inicioCD, 0xffffffff), true);
    this.grava(new Uint8Array(fim.buffer));
  }
}

async function limparAntigos(raiz) {
  for await (const nome of raiz.keys()) {
    if (nome.startsWith("migracao-")) await raiz.removeEntry(nome, { recursive: true }).catch(() => {});
  }
}

async function baixarTexto(nome) {
  const r = await fetch(nome);
  if (!r.ok) throw new Error(`Falha ao baixar ${nome}`);
  return r.text();
}

async function executar(itens) {
  avisar({ tipo: "etapa", texto: "Carregando o conversor (só demora na primeira vez)..." });
  const raiz = await navigator.storage.getDirectory();
  await limparAntigos(raiz);
  await conferirEspaco(itens);
  const trabalho = await raiz.getDirectoryHandle(`migracao-${Date.now()}`, { create: true });
  const blobs = await (await trabalho.getFileHandle("blobs.bin", { create: true })).createSyncAccessHandle();
  const zipArq = await trabalho.getFileHandle("saida.zip", { create: true });
  const zipAlca = await zipArq.createSyncAccessHandle();

  const py = await loadPyodide({ indexURL: "https://cdn.jsdelivr.net/pyodide/v0.28.3/full/" });
  if (itens.some((i) => /\.(tar\.xz|txz)$/i.test(i.caminho))) await py.loadPackage("lzma");

  let cursorBlobs = 0;
  let semEspaco = false;
  const falhas = [];
  const dados = {};
  py.registerJsModule("ponte", {
    escrever(bytes) {
      const pos = cursorBlobs;
      try {
        gravar(blobs, bytes, pos);
      } catch (erro) {
        semEspaco = true;
        throw erro;
      }
      cursorBlobs += bytes.length;
      return pos;
    },
    relatorio(json) {
      const d = JSON.parse(json);
      dados[d.nome] = d;
    },
    buscar(url) {
      const x = new XMLHttpRequest();
      x.open("GET", url, false);
      x.send();
      if (x.status !== 200) throw new Error(`HTTP ${x.status}`);
      return x.responseText;
    },
    log(msg = "") {
      const texto = String(msg);
      if (texto.includes("FALHA em")) falhas.push(texto.trim());
      if (texto.trim()) avisar({ tipo: "log", texto: texto.trim() });
    },
  });

  py.FS.mkdirTree(`${APP}/ENTRADA`);
  py.FS.mount(py.FS.filesystems.WORKERFS, { blobs: itens.map((i) => ({ name: i.caminho, data: i.arquivo })) }, `${APP}/ENTRADA`);
  py.FS.writeFile(`${APP}/migrar.py`, await baixarTexto("migrar.py"));
  py.FS.writeFile(`${APP}/camada_mta.json`, await baixarTexto("camada_mta.json"));
  const runner = await baixarTexto("web_runner.py");

  avisar({ tipo: "etapa", texto: "Convertendo os resources..." });
  py.runPython(`import sys\nsys.dont_write_bytecode = True\nsys.path.insert(0, "${APP}")`);
  py.runPython(runner);
  if (semEspaco) throw new SemEspaco();

  const arquivos = listar(py, `${APP}/SAIDA`);
  const relatorios = arquivos
    .filter((a) => a.rel.endsWith("relatorio.txt"))
    .map((a) => {
      const nome = a.rel.replace(/\/relatorio\.txt$/, "");
      return { ...dados[nome], nome, texto: py.FS.readFile(a.caminho, { encoding: "utf8" }) };
    });

  avisar({ tipo: "etapa", texto: "Montando o .zip final..." });
  const zip = new Zip(zipAlca);
  let feitos = 0;
  for (const a of arquivos) {
    const stub = a.tamanho === TAM_STUB ? ehStub(py, a.caminho) : null;
    if (stub) {
      zip.adicionar(a.rel, stub.tamanho, function* () {
        for (let at = 0; at < stub.tamanho; at += BLOCO) {
          const parte = new Uint8Array(Math.min(BLOCO, stub.tamanho - at));
          if (blobs.read(parte, { at: stub.posicao + at }) !== parte.length) throw new Error("Falha ao ler o arquivo temporário.");
          yield parte;
        }
      });
    } else {
      const dados = py.FS.readFile(a.caminho);
      zip.adicionar(a.rel, dados.length, function* () { yield dados; });
    }
    feitos++;
    if (feitos % 50 === 0 || feitos === arquivos.length) avisar({ tipo: "zip", feitos, total: arquivos.length });
  }
  zip.fechar();
  zipAlca.flush();
  zipAlca.close();
  blobs.close();
  const arquivo = await zipArq.getFile();
  avisar({ tipo: "fim", arquivo, relatorios, falhas });
}

onmessage = (e) => {
  executar(e.data.itens).catch((erro) => {
    const quota = erro?.name === "QuotaExceededError" || /quota/i.test(String(erro));
    avisar({
      tipo: "erro",
      texto: quota ? "O navegador ficou sem espaço. Libere espaço no disco e tente de novo. Em aba anônima o limite é bem menor: use uma aba normal." : String(erro?.message || erro),
    });
  });
};
