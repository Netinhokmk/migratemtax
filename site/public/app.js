const EXTENSOES = [".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz", ".tar", ".zip"];
const COMPILAR = "[compilar]";
const REPO_URL = "https://github.com/Netinhokmk/migratemtax";
const PASSOS = ["Pegar os arquivos", "Migrar", "Baixar o resultado", "Conta e Key no MTAX", "Montar o servidor", "Logo e banners", "Ligar e testar"];
const TOTAL = PASSOS.length;
const VANTAGENS = [
  ["Tudo criptografado", "Todos os seus assets ficam 100% criptografados: png, fontes, txd, dff, .lua e .map."],
  ["Anti-cheat nativo", "Configure cada permissão de forma simples e não dependa de serviços de anti-cheat para proteger seu servidor."],
  ["DX ou HTML", "Crie suas interfaces com DX ou HTML. O MTAX conta com um CEF atualizado, do mesmo modelo do FiveM."],
  ["Proteção gratuita", "Não pague mensalidade: compile scripts e modelagens de graça. Não existe encomendar algo e ficar desprotegido."],
  ["Proteção para lojas", "Lojas que usam a proteção da plataforma têm zero delay e nenhuma gambiarra para funcionar."],
  ["Suporte e sugestões", "A comunidade é ativa. Tem alguma ideia do que adicionar na plataforma? Faça sua sugestão."],
  ["FPS ilimitado", "Acostumado com FPS a 60? Aqui não: o céu é o limite."],
  ["Projetos temáticos", "Estão trabalhando para migrar mapas de jogos famosos, como Bully, Farming Simulator, The Last of Us e Vice City. Quer um projeto temático? Faça sua sugestão."],
];

const $ = (id) => document.getElementById(id);
const zona = $("zona");
const fila = $("fila");
const listaFila = $("lista-fila");
const painel = $("painel");
const inputPasta = $("input-pasta");
const inputArquivo = $("input-arquivo");
const btnContinuar = $("btn-continuar");
const aviso = $("aviso-fila");

let itens = [];
let worker = null;
let urlZip = null;
let migrado = false;
let passo = 0;
let timerDicas = null;
let dicaAtual = 0;
const lerFeitos = () => new Set(JSON.parse(localStorage.getItem("passos-feitos") || "[]"));

const ehBackup = (nome) => EXTENSOES.some((e) => nome.toLowerCase().endsWith(e));

function formatarTamanho(b) {
  if (b >= 1024 ** 3) return `${(b / 1024 ** 3).toFixed(2)} GB`;
  if (b >= 1024 ** 2) return `${(b / 1024 ** 2).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(b / 1024))} KB`;
}

function mostrarEstado(estado) {
  for (const id of ["zona", "fila", "painel"]) $(id).hidden = id !== estado;
  atualizarRodape();
}

function nomeLivre(nome) {
  const usados = new Set(itens.map((i) => i.nome.toLowerCase()));
  if (!usados.has(nome.toLowerCase())) return nome;
  const m = EXTENSOES.find((e) => nome.toLowerCase().endsWith(e)) || "";
  const base = m ? nome.slice(0, -m.length) : nome;
  let n = 2;
  while (usados.has(`${base} (${n})${m}`.toLowerCase())) n++;
  return `${base} (${n})${m}`;
}

function adicionarPasta(nome, arquivos) {
  if (!arquivos.length) return;
  const livre = nomeLivre(nome);
  itens.push({
    nome: livre,
    pasta: true,
    arquivos,
    tamanho: arquivos.reduce((s, a) => s + a.arquivo.size, 0),
    compilar: false,
  });
}

function adicionarArquivo(arquivo) {
  itens.push({ nome: nomeLivre(arquivo.name), pasta: false, arquivo, tamanho: arquivo.size, compilar: false });
}

function adicionarSoltos(arquivos) {
  const ignorados = [];
  for (const a of arquivos) {
    if (ehBackup(a.name)) adicionarArquivo(a);
    else ignorados.push(a.name);
  }
  return ignorados;
}

function lerLote(leitor) {
  return new Promise((ok, erro) => leitor.readEntries(ok, erro));
}

async function lerEntrada(entrada, prefixo, saida) {
  if (entrada.isFile) {
    const arquivo = await new Promise((ok, erro) => entrada.file(ok, erro));
    saida.push({ rel: prefixo + entrada.name, arquivo });
    return;
  }
  const leitor = entrada.createReader();
  for (let lote = await lerLote(leitor); lote.length; lote = await lerLote(leitor)) {
    for (const filho of lote) await lerEntrada(filho, `${prefixo}${entrada.name}/`, saida);
  }
}

async function receberSoltura(dataTransfer) {
  const entradas = [...dataTransfer.items].map((i) => i.webkitGetAsEntry?.()).filter(Boolean);
  const soltos = [];
  zona.classList.add("lendo");
  for (const entrada of entradas) {
    if (entrada.isFile) {
      soltos.push(await new Promise((ok, erro) => entrada.file(ok, erro)));
      continue;
    }
    const arquivos = [];
    await lerEntrada(entrada, "", arquivos);
    adicionarPasta(entrada.name, arquivos);
  }
  zona.classList.remove("lendo");
  finalizarAdicao(adicionarSoltos(soltos));
}

function receberInputPasta(arquivos) {
  const grupos = new Map();
  for (const arquivo of arquivos) {
    const [topo] = arquivo.webkitRelativePath.split("/");
    if (!grupos.has(topo)) grupos.set(topo, []);
    grupos.get(topo).push({ rel: arquivo.webkitRelativePath, arquivo });
  }
  for (const [nome, lista] of grupos) adicionarPasta(nome, lista);
  finalizarAdicao([]);
}

function finalizarAdicao(ignorados) {
  aviso.hidden = !ignorados.length;
  aviso.textContent = ignorados.length
    ? `Ignorado (não é pasta, .zip ou .tar): ${ignorados.slice(0, 3).join(", ")}${ignorados.length > 3 ? ` e mais ${ignorados.length - 3}` : ""}.`
    : "";
  desenharFila();
}

function desenharFila() {
  if (!itens.length) {
    mostrarEstado("zona");
    return;
  }
  mostrarEstado("fila");
  listaFila.replaceChildren(
    ...itens.map((item, indice) => {
      const li = document.createElement("li");
      const info = document.createElement("div");
      info.className = "fila-info";
      const nome = document.createElement("strong");
      nome.textContent = item.nome;
      const meta = document.createElement("span");
      meta.textContent = item.pasta
        ? `Pasta · ${item.arquivos.length.toLocaleString("pt-BR")} arquivos · ${formatarTamanho(item.tamanho)}`
        : `Backup compactado · ${formatarTamanho(item.tamanho)}`;
      info.append(nome, meta);

      const rotulo = document.createElement("label");
      rotulo.className = "fila-compilar";
      const caixa = document.createElement("input");
      caixa.type = "checkbox";
      const jaCompilar = item.nome.toLowerCase() === COMPILAR;
      caixa.checked = item.compilar || jaCompilar;
      caixa.disabled = jaCompilar;
      caixa.addEventListener("change", () => { item.compilar = caixa.checked; });
      rotulo.append(caixa, "Vai compilar");
      rotulo.title = "Deixa as linhas :mta comentadas no manifest";

      const remover = document.createElement("button");
      remover.type = "button";
      remover.className = "fila-remover";
      remover.setAttribute("aria-label", `Remover ${item.nome}`);
      remover.textContent = "×";
      remover.addEventListener("click", () => {
        itens.splice(indice, 1);
        desenharFila();
      });
      li.append(info, rotulo, remover);
      return li;
    }),
  );
  $("fila-total").textContent = `${itens.length} ${itens.length === 1 ? "item" : "itens"} · ${formatarTamanho(itens.reduce((s, i) => s + i.tamanho, 0))}`;
}

function montarEntrada() {
  const saida = [];
  for (const item of itens) {
    const prefixo = item.compilar ? "[COMPILAR]/" : "";
    if (!item.pasta) {
      saida.push({ caminho: prefixo + item.nome, arquivo: item.arquivo });
      continue;
    }
    for (const { rel, arquivo } of item.arquivos) {
      const resto = rel.slice(rel.indexOf("/") + 1);
      saida.push({ caminho: `${prefixo}${item.nome}/${resto}`, arquivo });
    }
  }
  return saida;
}

function linhaLog(texto) {
  const log = $("log");
  log.textContent += `${texto}\n`;
  log.scrollTop = log.scrollHeight;
}

function iniciar() {
  migrado = false;
  $("processando").hidden = false;
  $("erro").hidden = true;
  $("log").textContent = "";
  $("barra").classList.add("indeterminada");
  $("barra-valor").style.width = "";
  if (urlZip) URL.revokeObjectURL(urlZip);

  worker = new Worker("worker.js", { type: "module" });
  mostrarEstado("painel");
  iniciarDicas();
  worker.onmessage = ({ data }) => {
    if (data.tipo === "etapa") $("etapa").textContent = data.texto;
    if (data.tipo === "log") {
      linhaLog(data.texto);
      if (data.texto.startsWith("===")) $("etapa").textContent = `Convertendo ${data.texto.replace(/=/g, "").trim()}...`;
    }
    if (data.tipo === "zip") {
      $("barra").classList.remove("indeterminada");
      $("barra-valor").style.width = `${Math.round((data.feitos / data.total) * 100)}%`;
    }
    if (data.tipo === "fim") concluir(data);
    if (data.tipo === "erro") falhar(data.texto);
  };
  worker.onerror = (e) => falhar(e.message || "Erro inesperado no conversor.");
  worker.postMessage({ itens: montarEntrada() });
}

function mostrarDica() {
  const [titulo, texto] = VANTAGENS[dicaAtual];
  $("dica-titulo").textContent = titulo;
  $("dica-texto").textContent = texto;
  $("dica-pontos").replaceChildren(...VANTAGENS.map((_, i) => {
    const ponto = document.createElement("span");
    if (i === dicaAtual) ponto.className = "ativo";
    return ponto;
  }));
}

function iniciarDicas() {
  clearInterval(timerDicas);
  dicaAtual = 0;
  mostrarDica();
  timerDicas = setInterval(() => {
    if (!worker) {
      clearInterval(timerDicas);
      return;
    }
    dicaAtual = (dicaAtual + 1) % VANTAGENS.length;
    mostrarDica();
  }, 7000);
}

function falhar(texto) {
  worker?.terminate();
  worker = null;
  $("processando").hidden = true;
  $("erro").hidden = false;
  $("erro-texto").textContent = texto;
  atualizarRodape();
}

function el(tag, classe, texto) {
  const n = document.createElement(tag);
  if (classe) n.className = classe;
  if (texto !== undefined) n.textContent = texto;
  return n;
}

function juntar(relatorios, chave) {
  const multiplos = relatorios.length > 1;
  return relatorios.flatMap((r) => (r[chave] || []).map((item) => ({ item, backup: multiplos ? r.nome : "" })));
}

function linhaResource(nome, backup, detalhes, rotulo) {
  const linha = el("div", "rel-linha");
  const topo = el("div", "rel-linha-topo");
  if (rotulo) topo.append(el("span", `rel-selo ${rotulo.toLowerCase()}`, rotulo));
  topo.append(el("code", "", nome));
  if (backup) topo.append(el("span", "rel-backup", backup));
  linha.append(topo);
  if (detalhes.length) {
    const lista = el("ul", "rel-arquivos");
    for (const d of detalhes.slice(0, 10)) lista.append(el("li", "", d));
    if (detalhes.length > 10) lista.append(el("li", "rel-mais", `e mais ${detalhes.length - 10}`));
    linha.append(lista);
  }
  return linha;
}

function grupo({ titulo, porque, acao, linhas, tom = "", aberto = true }) {
  const det = el("details", `rel-grupo ${tom}`);
  det.open = aberto;
  const resumo = el("summary");
  resumo.append(el("span", "", titulo), el("span", "rel-conta", linhas.length.toLocaleString("pt-BR")));
  det.append(resumo);
  if (porque || acao) {
    const caixa = el("div", "rel-motivo");
    if (porque) {
      const p = el("p");
      p.append(el("strong", "", "Por quê: "), porque);
      caixa.append(p);
    }
    if (acao) {
      const p = el("p", "rel-acao");
      p.append(el("strong", "", "O que fazer: "), acao);
      caixa.append(p);
    }
    det.append(caixa);
  }
  const lista = el("div", "rel-lista");
  lista.append(...linhas);
  det.append(lista);
  return det;
}

function desenharRelatorio(relatorios, falhas) {
  const compilados = juntar(relatorios, "compilados");
  const modelos = juntar(relatorios, "modelos");
  const hyper = juntar(relatorios, "hyper");
  const convertidos = juntar(relatorios, "convertidos");
  const avisosDe = (niveis) => convertidos.flatMap(({ item, backup }) =>
    item.avisos.filter((a) => niveis.includes(a.nivel)).map((a) => ({ ...a, resource: item.resource, backup })));
  const graves = avisosDe(["BLOQUEIO", "ERRO"]);
  const avisos = avisosDe(["AVISO"]);
  const prontos = convertidos.length + juntar(relatorios, "ja_migrados").length;
  const naoMigraram = compilados.length + modelos.length + hyper.length;
  const conteudo = $("rel-conteudo");
  conteudo.replaceChildren();

  const pendencias = naoMigraram + graves.length;
  $("rel-titulo").textContent = pendencias
    ? `Quase lá: ${prontos.toLocaleString("pt-BR")} ${prontos === 1 ? "sistema pronto" : "sistemas prontos"}`
    : `Deu tudo certo: ${prontos.toLocaleString("pt-BR")} ${prontos === 1 ? "sistema pronto" : "sistemas prontos"}`;
  $("rel-sub").textContent = pendencias
    ? "Baixe o que ficou pronto. Logo abaixo está o que precisa da sua atenção e o que fazer."
    : "Nenhum sistema ficou para trás. Baixe o arquivo e continue.";

  if (compilados.length) {
    conteudo.append(grupo({
      titulo: "Não migraram: sistemas compilados (.lua ou .luac)",
      porque: "o código está compilado, então não dá para ler nem converter.",
      acao: "entre em contato com a loja responsável para que migre o sistema para o MTAX.",
      tom: "ruim",
      linhas: compilados.map(({ item, backup }) => linhaResource(item.resource, backup, item.arquivos)),
    }));
  }
  if (modelos.length) {
    conteudo.append(grupo({
      titulo: "Não migraram: modelos criptografados",
      porque: "os arquivos .dff, .txd ou .col estão criptografados e o MTAX precisa deles abertos.",
      acao: "entre em contato com a loja responsável. Se foi encomenda, peça os modelos sem criptografia.",
      tom: "ruim",
      linhas: modelos.map(({ item, backup }) => linhaResource(item.resource, backup, item.arquivos)),
    }));
  }
  if (hyper.length) {
    conteudo.append(grupo({
      titulo: "Não migraram: sistemas da Hyper Scripts",
      porque: "sistemas com [hs] no nome ficam separados e não passam pela conversão.",
      acao: "fale com a Hyper Scripts no Discord.",
      tom: "ruim",
      linhas: hyper.map(({ item, backup }) => linhaResource(item, backup, [])),
    }));
  }
  if (graves.length) {
    conteudo.append(grupo({
      titulo: "Migraram, mas falta um detalhe",
      porque: "estas partes foram removidas do manifest ou não foram encontradas.",
      acao: "corrija no resource e migre de novo, ou ajuste o mtaxmanifest.lua na mão.",
      tom: "atencao",
      linhas: graves.map((a) => linhaResource(a.resource, a.backup, [a.msg], a.nivel)),
    }));
  }

  const conflitos = juntar(relatorios, "bancos_conflito");
  if (conflitos.length) {
    conteudo.append(grupo({
      titulo: "Bancos de dados com nome repetido",
      porque: "dois sistemas usavam um banco com o mesmo nome. Separamos para nenhum apagar o outro.",
      acao: "ajuste o dbConnect destes sistemas para o novo caminho, dentro da pasta databases.",
      tom: "atencao",
      linhas: conflitos.map(({ item, backup }) => linhaResource(item, backup, [])),
    }));
  }
  const bancos = juntar(relatorios, "bancos");
  if (bancos.length) {
    conteudo.append(grupo({
      titulo: "Bancos de dados preservados",
      acao: "copie a pasta databases do .zip para a pasta do servidor, junto do server.cfg. Sem isso, os sistemas começam zerados.",
      aberto: false,
      linhas: bancos.map(({ item, backup }) => linhaResource(item, backup, [])),
    }));
  }
  if (avisos.length) {
    conteudo.append(grupo({
      titulo: "Avisos",
      porque: "recursos do MTA que o MTAX não suporta. Teste estes sistemas com atenção.",
      aberto: false,
      linhas: avisos.map((a) => linhaResource(a.resource, a.backup, [a.msg], a.nivel)),
    }));
  }
  $("falhas").hidden = !falhas.length;
  $("falhas").textContent = falhas.join("\n");
}

function concluir({ arquivo, relatorios, falhas }) {
  worker.terminate();
  worker = null;
  if (!relatorios.length && !falhas.length) {
    falhar("Não encontramos nenhum sistema. Confira se você escolheu a pasta do servidor.");
    return;
  }
  urlZip = URL.createObjectURL(arquivo);
  $("baixar").href = urlZip;
  $("baixar").download = "migracao-mtax.zip";
  $("baixar-tamanho").textContent = formatarTamanho(arquivo.size);
  desenharRelatorio(relatorios, falhas);
  migrado = true;
  $("sem-resultado").hidden = true;
  $("relatorio").hidden = false;
  concluirPasso();
  location.hash = "#3";
}

function recomecar() {
  worker?.terminate();
  worker = null;
  itens = [];
  migrado = false;
  $("relatorio").hidden = true;
  $("sem-resultado").hidden = false;
  desenharFila();
  location.hash = "#2";
}

function concluirPasso() {
  const feitos = lerFeitos();
  feitos.add(passo);
  localStorage.setItem("passos-feitos", JSON.stringify([...feitos]));
}

function atualizarRodape() {
  const dica = $("rodape-dica");
  dica.textContent = "";
  btnContinuar.hidden = false;
  btnContinuar.disabled = false;
  btnContinuar.textContent = passo === TOTAL ? "Concluir" : "Continuar";
  if (passo === 1 && !localStorage.getItem("local")) {
    btnContinuar.disabled = true;
    dica.textContent = "Escolha uma opção para continuar";
  }
  if (passo === 2) {
    const rodando = Boolean(worker);
    if (rodando) {
      btnContinuar.disabled = true;
      btnContinuar.textContent = "Migrando...";
    } else if (migrado) {
      btnContinuar.textContent = "Continuar";
    } else if (itens.length) {
      btnContinuar.textContent = "Migrar para MTAX";
    } else {
      btnContinuar.disabled = true;
      dica.textContent = "Arraste seu servidor para continuar";
    }
  }
}

function desenharTrilha() {
  const feitos = lerFeitos();
  let atual = 1;
  while (feitos.has(atual) && atual < TOTAL) atual++;
  $("btn-comecar").href = `#${atual}`;
  $("btn-comecar").textContent = feitos.size ? "Continuar de onde parei" : "Começar";
  $("trilha").replaceChildren(...PASSOS.map((nome, i) => {
    const n = i + 1;
    const li = document.createElement("li");
    const no = document.createElement("a");
    no.href = `#${n}`;
    no.setAttribute("aria-label", `Passo ${n}: ${nome}`);
    no.className = `no${feitos.has(n) ? " feito" : n === atual ? " atual" : ""}`;
    if (feitos.has(n)) no.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 13l4 4L19 7"/></svg>';
    else no.textContent = n;
    const texto = document.createElement("span");
    texto.textContent = nome;
    li.append(no, texto);
    return li;
  }));
}

function irParaHash() {
  const irVantagens = location.hash === "#vantagens";
  const n = Number(location.hash.slice(1));
  passo = Number.isInteger(n) && n >= 0 && n <= TOTAL ? n : 0;
  for (let i = 0; i <= TOTAL; i++) $(`tela-${i}`).hidden = i !== passo;
  $("progresso").hidden = passo === 0;
  $("rodape").hidden = passo === 0;
  $("site-rodape").hidden = passo !== 0;
  $("progresso-valor").style.width = `${(passo / TOTAL) * 100}%`;
  $("progresso-texto").textContent = `Passo ${passo} de ${TOTAL}`;
  $("btn-voltar").href = `#${Math.max(passo - 1, 0)}`;
  if (passo === 0) desenharTrilha();
  atualizarRodape();
  $("link-vantagens").hidden = passo !== 0;
  if (irVantagens) $("vantagens").scrollIntoView();
  else scrollTo(0, 0);
}

function marcarLocal(local) {
  localStorage.setItem("local", local);
  for (const b of document.querySelectorAll(".opcao")) b.setAttribute("aria-checked", String(b.dataset.local === local));
  $("instrucao-local").hidden = false;
  for (const d of document.querySelectorAll("#instrucao-local [data-local]")) d.hidden = d.dataset.local !== local;
  atualizarRodape();
}

for (const evento of ["dragover", "drop"]) {
  window.addEventListener(evento, (e) => e.preventDefault());
}
const areaSoltar = $("tela-2");
const aceitaSoltar = () => painel.hidden;
for (const evento of ["dragenter", "dragover"]) {
  areaSoltar.addEventListener(evento, () => zona.classList.toggle("ativa", aceitaSoltar()));
}
areaSoltar.addEventListener("dragleave", (e) => {
  if (!areaSoltar.contains(e.relatedTarget)) zona.classList.remove("ativa");
});
areaSoltar.addEventListener("drop", (e) => {
  zona.classList.remove("ativa");
  if (!aceitaSoltar()) return;
  receberSoltura(e.dataTransfer).catch((erro) => finalizarAdicao([String(erro)]));
});

$("btn-pasta").addEventListener("click", () => inputPasta.click());
$("btn-arquivo").addEventListener("click", () => inputArquivo.click());
$("btn-mais-pasta").addEventListener("click", () => inputPasta.click());
$("btn-mais-arquivo").addEventListener("click", () => inputArquivo.click());
inputPasta.addEventListener("change", () => {
  receberInputPasta([...inputPasta.files]);
  inputPasta.value = "";
});
inputArquivo.addEventListener("change", () => {
  finalizarAdicao(adicionarSoltos([...inputArquivo.files]));
  inputArquivo.value = "";
});
btnContinuar.addEventListener("click", () => {
  if (passo === 2 && !migrado && itens.length) {
    iniciar();
    return;
  }
  concluirPasso();
  location.hash = passo === TOTAL ? "#0" : `#${passo + 1}`;
});
$("btn-limpar").addEventListener("click", recomecar);
$("btn-cancelar").addEventListener("click", () => {
  worker?.terminate();
  worker = null;
  desenharFila();
});
$("btn-de-novo").addEventListener("click", recomecar);
$("btn-erro-voltar").addEventListener("click", desenharFila);
for (const b of document.querySelectorAll(".btn-copiar")) {
  b.addEventListener("click", async () => {
    await navigator.clipboard.writeText($(b.dataset.copiar).textContent);
    b.textContent = "Copiado!";
  });
}
for (const b of document.querySelectorAll(".opcao")) b.addEventListener("click", () => marcarLocal(b.dataset.local));
for (const c of document.querySelectorAll("[data-tarefa]")) {
  const chave = `tarefa-${c.dataset.tarefa}`;
  c.checked = localStorage.getItem(chave) === "1";
  c.addEventListener("change", () => localStorage.setItem(chave, c.checked ? "1" : "0"));
}
for (const l of document.querySelectorAll("[data-repo]")) l.href = REPO_URL;
window.addEventListener("hashchange", irParaHash);
window.addEventListener("beforeunload", (e) => { if (worker) e.preventDefault(); });

if (!navigator.storage?.getDirectory) {
  zona.hidden = true;
  $("sem-suporte").hidden = false;
}

if (localStorage.getItem("local")) marcarLocal(localStorage.getItem("local"));
irParaHash();
