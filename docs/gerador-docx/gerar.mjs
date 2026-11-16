// Gera o TCC em formato de artigo (.docx, ABNT NBR 6022/14724) a partir do vault.
//
//   cd docs/gerador-docx && npm install && npm run gerar
//
// Saída: docs/DroidServer_TCC_artigo.docx
// Os diagramas Mermaid são renderizados (Chrome do sistema) e guardados em
// docs/obsidian-valt/figuras/diagramas/ — só são refeitos quando o código muda.
// Lacunas ([RESULTADO]), referências a conferir (⚠) e dados a preencher
// ([Nome do(a) orientador(a)], [e-mail]) saem destacados em amarelo.

import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import JSZip from "jszip";
import { marked } from "marked";
import {
  AlignmentType, BorderStyle, Document, Footer, FootnoteReferenceRun, Header, HeadingLevel, ImageRun,
  LevelFormat, Math as Equacao, MathFraction, MathRun, MathSubScript, MathSum, Packer, PageBreak, PageNumber, Paragraph, ShadingType, Table, TableCell, TableRow,
  TextRun, WidthType,
} from "docx";

const AQUI = path.dirname(fileURLToPath(import.meta.url));
const VAULT = path.resolve(AQUI, "../obsidian-valt");
const SAIDA = path.resolve(AQUI, "../DroidServer_TCC_artigo.docx");
const DIAGRAMAS = path.join(VAULT, "figuras", "diagramas");
const CHROME = process.env.CHROME || "/usr/bin/google-chrome";
const EQUACOES_DIR = path.join(VAULT, "figuras", "equacoes");
// EQUACOES=word gera equação nativa do Word (OMML). O padrão é imagem, que abre
// em qualquer editor (o WordCraft ainda não tem editor de equações).
const EQUACAO_NATIVA = process.env.EQUACOES === "word";

// ---------------------------------------------------------------------------
// Dados da capa / folha de rosto (o que estiver entre colchetes sai destacado)
// ---------------------------------------------------------------------------
const META = {
  instituicao: "CENTRO UNIVERSITÁRIO DO NORTE — UNINORTE",
  curso: "ENGENHARIA DA COMPUTAÇÃO",
  autor: "JOÃO PEDRO CORREIA MARTINS",
  autorNome: "João Pedro Correia Martins",
  titulo: "DroidServer: orquestração de servidores virtuais privados em smartphones Android reaproveitados",
  natureza: "Artigo científico apresentado ao curso de Engenharia da Computação do Centro Universitário do " +
    "Norte — Uninorte, como requisito parcial para obtenção do título de Bacharel em Engenharia da Computação.",
  orientador: "[Nome do(a) orientador(a)]",
  local: "MANAUS – AM",
  ano: "2026",
  notaAutor: "Graduando em Engenharia da Computação pelo Centro Universitário do Norte — Uninorte. E-mail: [e-mail].",
};

// Ordem do artigo (NBR 6022): resumo/abstract, texto, referências, glossário
const ARQUIVOS = [
  "00-resumo.md", "01-introducao.md", "02-problema-de-pesquisa.md", "03-objetivos.md", "04-justificativa.md",
  "05-referencial-teorico.md", "06-trabalhos-relacionados.md", "07-metodologia.md", "08-prototipacao.md",
  "09-avaliacao-experimental.md", "10-limitacoes-e-trabalhos-futuros.md", "12-referencias.md", "11-glossario.md",
];

// ---------------------------------------------------------------------------
// Medidas (twips: 1 cm = 567; imagens em px a 96 dpi)
// ---------------------------------------------------------------------------
const CM = 567;
const LARGURA_TEXTO = 9070;            // A4 (21 cm) - 3 cm - 2 cm = 16 cm
const LARGURA_IMG_PX = 605;            // 16 cm
const ALTURA_IMG_PX = 720;             // ~19 cm
const FONTE = "Times New Roman";
const MONO = "Courier New";
const PT = (n) => n * 2;               // docx usa meio-ponto
const DESTAQUE = /(\[RESULTAD[OE][^\]]*\]|\[RESULT[^\]]*\]|⚠|\[Nome do\(a\)[^\]]*\]|\[e-mail\])/;

// ---------------------------------------------------------------------------
// Pré-processamento do Markdown do Obsidian
// ---------------------------------------------------------------------------
// "~13×" é aproximação, não tachado: escapa o til simples fora de código
function escaparTil(md) {
  let emBloco = false;
  return md.split("\n").map((linha) => {
    if (/^```/.test(linha)) { emBloco = !emBloco; return linha; }
    if (emBloco) return linha;
    return linha.split(/(`[^`]*`)/).map((parte) => (parte.startsWith("`") ? parte
      : parte.replace(/(?<!~)~(?!~)/g, "\\~"))).join("");
  }).join("\n");
}

function lerMd(nome) {
  return escaparTil(fs.readFileSync(path.join(VAULT, nome), "utf8"))
    .replace(/!\[\[([^\]|]+)(\|[^\]]*)?\]\]/g, (_, alvo) => `![](${alvo.trim()})`)       // embed
    .replace(/\[\[([^\]|]+)\|([^\]]+)\]\]/g, "$2")                                        // [[a|b]]
    .replace(/\[\[([^\]]+)\]\]/g, (_, a) => a.replace(/\.md$/, "").replace(/^\d+-/, "")); // [[a]]
}

// Numeração sequencial de figuras, quadros e tabelas (a do vault mistura 1, 2... e 9.1, 9.2...)
const RE_LEGENDA = /^\*(Figura|Quadro|Tabela) ([\d.]+) — /;
const renumeracao = {};
{
  const cont = { Figura: 0, Quadro: 0, Tabela: 0 };
  for (const nome of ARQUIVOS) {
    for (const linha of lerMd(nome).split("\n")) {
      const m = linha.match(RE_LEGENDA);
      if (m) renumeracao[`${m[1]} ${m[2]}`] = `${m[1]} ${++cont[m[1]]}`;
    }
  }
}
const renumerar = (t) => t.replace(/\b(Figura|Quadro|Tabela) (\d+(?:\.\d+)?)/g,
  (x, tipo, n) => renumeracao[`${tipo} ${n}`] || x);

const decodificar = (t) => t.replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
  .replace(/&quot;/g, '"').replace(/&#39;/g, "'");

// ---------------------------------------------------------------------------
// Texto em linha -> TextRun[]
// ---------------------------------------------------------------------------
function trechos(texto, fmt) {
  const saida = [];
  for (const parte of renumerar(decodificar(texto)).split(DESTAQUE)) {
    if (!parte) continue;
    const destacar = DESTAQUE.test(parte);
    saida.push(new TextRun({ text: parte, ...fmt, ...(destacar ? { highlight: "yellow" } : {}) }));
  }
  return saida;
}

function emLinha(tokens, fmt = {}) {
  const runs = [];
  for (const t of tokens || []) {
    switch (t.type) {
      case "text":
        runs.push(...(t.tokens ? emLinha(t.tokens, fmt) : trechos(t.text, fmt)));
        break;
      case "escape":
        runs.push(...trechos(t.text, fmt));
        break;
      case "strong":
        runs.push(...emLinha(t.tokens, { ...fmt, bold: true }));
        break;
      case "em":
        runs.push(...emLinha(t.tokens, { ...fmt, italics: true }));
        break;
      case "del":
        runs.push(...emLinha(t.tokens, { ...fmt, strike: true }));
        break;
      case "codespan":
        runs.push(...trechos(t.text, { ...fmt, font: MONO, size: PT(10.5) }));
        break;
      case "link":
        runs.push(...emLinha(t.tokens, fmt));
        break;
      case "br":
        runs.push(new TextRun({ break: 1 }));
        break;
      case "html":
        if (/<br\s*\/?>/i.test(t.text)) runs.push(new TextRun({ break: 1 }));
        else runs.push(...trechos(t.text.replace(/<[^>]+>/g, ""), fmt));
        break;
      case "image":
        break; // tratadas como bloco
      default:
        if (t.text) runs.push(...trechos(t.text, fmt));
    }
  }
  return runs;
}

const textoPuro = (tokens) => (tokens || []).map((t) => (t.tokens ? textoPuro(t.tokens) : t.text || "")).join("");

// ---------------------------------------------------------------------------
// Imagens e diagramas
// ---------------------------------------------------------------------------
function tamanhoPng(buf) {
  return { w: buf.readUInt32BE(16), h: buf.readUInt32BE(20) };
}

function paragrafoImagem(caminho) {
  const dados = fs.readFileSync(caminho);
  const { w, h } = tamanhoPng(dados);
  const escala = Math.min(1, LARGURA_IMG_PX / w, ALTURA_IMG_PX / h);
  return new Paragraph({
    alignment: AlignmentType.CENTER, keepNext: true, spacing: { line: 240, before: 0, after: 0 },
    children: [new ImageRun({ type: "png", data: dados,
      transformation: { width: Math.round(w * escala), height: Math.round(h * escala) } })],
  });
}

function renderizarMermaid(codigo) {
  fs.mkdirSync(DIAGRAMAS, { recursive: true });
  const hash = createHash("sha256").update(codigo).digest("hex").slice(0, 12);
  const png = path.join(DIAGRAMAS, `mermaid-${hash}.png`);
  if (!fs.existsSync(png)) {
    const tmp = fs.mkdtempSync(path.join(AQUI, ".mmd-"));
    try {
      fs.writeFileSync(path.join(tmp, "d.mmd"), codigo);
      fs.writeFileSync(path.join(tmp, "p.json"), JSON.stringify({ executablePath: CHROME, args: ["--no-sandbox"] }));
      fs.writeFileSync(path.join(tmp, "c.json"), JSON.stringify({ theme: "neutral", fontFamily: "Arial" }));
      execFileSync(path.join(AQUI, "node_modules/.bin/mmdc"),
        ["-i", path.join(tmp, "d.mmd"), "-o", png, "-p", path.join(tmp, "p.json"), "-c", path.join(tmp, "c.json"),
          "-b", "white", "-s", "3", "-w", "1100"], { stdio: "pipe" });
      console.log(`  diagrama renderizado: ${path.relative(VAULT, png)}`);
    } finally {
      fs.rmSync(tmp, { recursive: true, force: true });
    }
  }
  return png;
}

// ---------------------------------------------------------------------------
// Legendas (ABNT: título acima, fonte abaixo)
// ---------------------------------------------------------------------------
function separarLegenda(raw) {
  const texto = raw.trim().replace(/^\*/, "").replace(/\*$/, "");
  const m = texto.match(/^(Figura|Quadro|Tabela) ([\d.]+) — (.*)$/);
  if (!m) return null;
  let resto = m[3];
  let fonte = null;
  const iFonte = resto.search(/\bFonte:/);
  if (iFonte >= 0) {
    fonte = resto.slice(iFonte + 6).trim();
    resto = resto.slice(0, iFonte).trim();
  }
  // título = primeira frase; o restante vira nota
  const fimFrase = resto.search(/\.\s+[A-ZÁÉÍÓÚ(]/);
  const titulo = (fimFrase >= 0 ? resto.slice(0, fimFrase) : resto).replace(/\.$/, "");
  const nota = fimFrase >= 0 ? resto.slice(fimFrase + 1).trim() : "";
  // a fonte pode trazer, depois do ponto, um lembrete para o autor
  let lembrete = "";
  if (fonte) {
    const fimFonte = fonte.search(/\.\s+[A-ZÁÉÍÓÚ]/);
    if (fimFonte >= 0) {
      lembrete = fonte.slice(fimFonte + 1).trim();
      fonte = fonte.slice(0, fimFonte + 1);
    }
    fonte = fonte.charAt(0).toUpperCase() + fonte.slice(1);
    if (!fonte.endsWith(".")) fonte += ".";
  }
  return {
    rotulo: renumeracao[`${m[1]} ${m[2]}`] || `${m[1]} ${m[2]}`,
    titulo, nota, lembrete, fonte: fonte || "Elaborado pelo autor (2026).",
  };
}

const legendaAcima = (l) => new Paragraph({
  style: "Legenda", keepNext: true,
  children: [new TextRun({ text: `${l.rotulo} — `, bold: true }), ...trechos(l.titulo, {})],
});
const legendaAbaixo = (l) => [
  ...(l.nota ? [new Paragraph({ style: "Fonte", children: trechos(`Nota: ${l.nota}`, {}) })] : []),
  ...(l.lembrete ? [new Paragraph({ style: "Fonte", children: trechos(`[Revisar: ${l.lembrete}]`, { highlight: "yellow" }) })] : []),
  new Paragraph({ style: "Fonte", children: [new TextRun({ text: "Fonte: " }), ...trechos(l.fonte, {})] }),
];

// ---------------------------------------------------------------------------
// Blocos
// ---------------------------------------------------------------------------
let instanciaLista = 0;
const NAO_NUMERADAS = ["resumo", "abstract", "referências", "glossário"];

function titulo(t, ctx) {
  const bruto = textoPuro(t.tokens).trim();
  if (t.depth === 1) {
    const chave = bruto.toLowerCase().replace(/^\d+\.\s*/, "");
    if (NAO_NUMERADAS.includes(chave)) {
      ctx.secao = chave;
      return [new Paragraph({ style: "TituloSemNumero", pageBreakBefore: chave === "referências" || chave === "glossário",
        children: [new TextRun({ text: chave.toUpperCase() })] })];
    }
    ctx.secao = "texto";
    const sem = { ...t, tokens: t.tokens.map((x, i) => (i === 0 && x.type === "text"
      ? { ...x, tokens: undefined, text: x.text.replace(/^(\d+)\.\s+/, "$1 ") } : x)) };
    return [new Paragraph({ heading: HeadingLevel.HEADING_1, children: emLinha(sem.tokens) })];
  }
  if (ctx.secao === "referências" || ctx.secao === "glossário") {
    return [new Paragraph({ heading: HeadingLevel.HEADING_3, children: emLinha(t.tokens) })];
  }
  return [new Paragraph({ heading: t.depth === 2 ? HeadingLevel.HEADING_2 : HeadingLevel.HEADING_3,
    children: emLinha(t.tokens) })];
}

function estiloParagrafo(ctx) {
  if (ctx.secao === "resumo" || ctx.secao === "abstract") return "Resumo";
  if (ctx.secao === "referências") return "Referencia";
  return "Corpo";
}

function lista(t, nivel, ctx) {
  const inst = t.ordered ? ++instanciaLista : 0;
  const saida = [];
  for (const item of t.items) {
    const blocosItem = item.tokens || [];
    let primeiro = true;
    for (const b of blocosItem) {
      if (b.type === "list") {
        saida.push(...lista(b, Math.min(nivel + 1, 2), ctx));
      } else if (b.type === "text" || b.type === "paragraph") {
        saida.push(new Paragraph({
          style: "ItemLista",
          ...(primeiro
            ? { numbering: t.ordered ? { reference: "numeros", level: nivel, instance: inst }
              : { reference: "marcadores", level: nivel } }
            : { indent: { left: 720 + nivel * 360 } }),
          children: emLinha(b.tokens || [{ type: "text", text: b.text }]),
        }));
        primeiro = false;
      } else if (b.type !== "space") {
        saida.push(...bloco(b, ctx));
      }
    }
  }
  return saida;
}

function tabela(t) {
  const linhas = [t.header, ...t.rows];
  const nCol = t.header.length;
  // ideal proporcional ao texto; mínimo = maior palavra da coluna (nada de "Questã/o")
  const textos = (c) => linhas.map((l) => textoPuro(l[c].tokens));
  const ideal = Array.from({ length: nCol }, (_, c) => Math.max(4, ...textos(c).map((t) => Math.min(60, t.length))));
  const minimo = Array.from({ length: nCol }, (_, c) => (Math.max(3, ...textos(c)
    .flatMap((t) => t.split(/\s+/)).map((w) => w.length)) + 1) * 110);
  let larguras = ideal.map((p) => (p / ideal.reduce((a, b) => a + b, 0)) * LARGURA_TEXTO);
  for (let volta = 0; volta < 5; volta++) {
    const fixas = larguras.map((w, c) => w <= minimo[c]);
    larguras = larguras.map((w, c) => (fixas[c] ? minimo[c] : w));
    const sobra = LARGURA_TEXTO - larguras.reduce((a, b, c) => a + (fixas[c] ? b : 0), 0);
    const somaLivres = larguras.reduce((a, b, c) => a + (fixas[c] ? 0 : b), 0);
    larguras = larguras.map((w, c) => (fixas[c] ? w : (w / somaLivres) * sobra));
  }
  larguras = larguras.map((w) => Math.floor(w));
  larguras[nCol - 1] += LARGURA_TEXTO - larguras.reduce((a, b) => a + b, 0);
  const borda = { style: BorderStyle.SINGLE, size: 4, color: "808080" };
  const bordas = { top: borda, bottom: borda, left: borda, right: borda };
  const celula = (cel, c, cabecalho) => new TableCell({
    width: { size: larguras[c], type: WidthType.DXA }, borders: bordas,
    margins: { top: 60, bottom: 60, left: 90, right: 90 },
    ...(cabecalho ? { shading: { type: ShadingType.CLEAR, color: "auto", fill: "E7E6E6" } } : {}),
    children: [new Paragraph({ style: "TextoTabela",
      children: emLinha(cel.tokens, cabecalho ? { bold: true } : {}) })],
  });
  return new Table({
    width: { size: LARGURA_TEXTO, type: WidthType.DXA }, columnWidths: larguras,
    rows: linhas.map((l, i) => new TableRow({ tableHeader: i === 0, cantSplit: true,
      children: l.map((cel, c) => celula(cel, c, i === 0)) })),
  });
}

function codigo(t) {
  return t.text.split("\n").map((linha, i, arr) => new Paragraph({
    style: "Codigo", keepNext: i < arr.length - 1,
    children: [new TextRun({ text: linha || " " })],
  }));
}

// Subconjunto de LaTeX usado no vault: \frac, \sum_x, _subscrito, \text{}, \Delta, \cdot, \%, \_
function latexParaMath(src) {
  let i = 0;
  const SIMBOLOS = { "\\Delta": "Δ", "\\cdot": "·", "\\%": "%", "\\_": "_", "\\times": "×" };
  function grupo() {           // {...} ou um único átomo
    if (src[i] === "{") { i++; const r = sequencia("}"); i++; return r; }
    return atomo();
  }
  function atomo() {
    if (src[i] === "\\") {
      const m = src.slice(i).match(/^\\([A-Za-z]+|.)/);
      i += m[0].length;
      const cmd = "\\" + m[1];
      if (cmd === "\\frac") { const num = grupo(); const den = grupo();
        return [new MathFraction({ numerator: num, denominator: den })]; }
      if (cmd === "\\text") { i++; let t = ""; while (src[i] !== "}") t += src[i++]; i++;
        return [new MathRun(t.replace(/\\_/g, "_"))]; }
      if (cmd === "\\sum") { let sub = []; if (src[i] === "_") { i++; sub = grupo(); }
        return [{ soma: sub }]; }
      return [new MathRun(SIMBOLOS[cmd] ?? m[1])];
    }
    const m = src.slice(i).match(/^[A-Za-z0-9.,]+|^./);   // "100", "CPU" num trecho só
    i += m[0].length;
    return [new MathRun(m[0])];
  }
  function sequencia(fim) {
    const itens = [];
    while (i < src.length && src[i] !== fim) {
      if (src[i] === " ") { i++; continue; }
      if (src[i] === "_" && itens.length) { i++; const base = itens.pop();
        itens.push(new MathSubScript({ children: [base], subScript: grupo() })); continue; }
      itens.push(...atomo());
    }
    // \sum: o corpo é o restante do grupo
    const k = itens.findIndex((x) => x && x.soma !== undefined);
    if (k >= 0) {
      const corpo = itens.splice(k + 1);
      itens[k] = new MathSum({ children: corpo, subScript: itens[k].soma });
    }
    return itens;
  }
  return sequencia(undefined);
}

function renderizarEquacao(latex) {
  fs.mkdirSync(EQUACOES_DIR, { recursive: true });
  const hash = createHash("sha256").update(latex).digest("hex").slice(0, 12);
  const png = path.join(EQUACOES_DIR, `equacao-${hash}.png`);
  if (!fs.existsSync(png)) {
    execFileSync("uv", ["run", "--with", "matplotlib", "python", path.join(AQUI, "render_equacao.py"), latex, png],
      { stdio: "pipe" });
    console.log(`  equação renderizada: ${path.relative(VAULT, png)}`);
  }
  return png;
}

let numeroEquacao = 0;
function equacao(latex) {
  if (!EQUACAO_NATIVA) {
    const dados = fs.readFileSync(renderizarEquacao(latex));
    const { w, h } = tamanhoPng(dados);
    const fator = 96 / 300;                          // PNG a 300 dpi -> tamanho real
    return new Paragraph({
      spacing: { line: 240, before: 240, after: 240 },
      tabStops: [{ type: "center", position: Math.round(LARGURA_TEXTO / 2) }, { type: "right", position: LARGURA_TEXTO }],
      children: [new TextRun({ text: "\t" }),
        new ImageRun({ type: "png", data: dados, transformation: { width: Math.round(w * fator), height: Math.round(h * fator) },
          altText: { name: `Equação ${numeroEquacao + 1}`, title: `Equação ${numeroEquacao + 1}`, description: latex } }),
        new TextRun({ text: `\t(${++numeroEquacao})` })],
    });
  }
  return new Paragraph({
    alignment: AlignmentType.CENTER, spacing: { line: 240, before: 240, after: 240 },
    children: [new Equacao({ children: latexParaMath(latex) }), new TextRun({ text: `\t(${++numeroEquacao})` })],
    tabStops: [{ type: "right", position: LARGURA_TEXTO }],
  });
}

function bloco(t, ctx) {
  switch (t.type) {
    case "heading": return titulo(t, ctx);
    case "paragraph": {
      const raw = t.raw.trim();
      if (raw.startsWith("$$") && raw.endsWith("$$")) return [equacao(raw.slice(2, -2).trim())];
      if (raw.startsWith("**Palavras-chave:**") || raw.startsWith("**Keywords:**")) {
        return [new Paragraph({ style: "PalavrasChave", children: emLinha(t.tokens) })];
      }
      return [new Paragraph({ style: estiloParagrafo(ctx), children: emLinha(t.tokens) })];
    }
    case "list": return lista(t, 0, ctx);
    case "table": return [tabela(t), new Paragraph({ style: "Fonte", children: [] })];
    case "code": return codigo(t);
    case "blockquote":
      if (/^>\s*\[!/.test(t.raw)) return []; // callout do Obsidian: nota editorial do vault
      return t.tokens.flatMap((b) => (b.type === "paragraph"
        ? [new Paragraph({ style: "Citacao", children: emLinha(b.tokens) })] : bloco(b, ctx)));
    case "hr": case "space": case "html": case "def": return [];
    default: return t.text ? [new Paragraph({ style: estiloParagrafo(ctx), children: trechos(t.text, {}) })] : [];
  }
}

// Elementos com legenda: figura (imagem ou Mermaid), tabela/quadro.
function elementoComLegenda(t) {
  if (t.type === "code" && t.lang === "mermaid") return { tipo: "mermaid", t };
  if (t.type === "table") return { tipo: "tabela", t };
  if (t.type === "paragraph" && t.tokens?.length === 1 && t.tokens[0].type === "image") return { tipo: "imagem", t };
  return null;
}

function converterArquivo(nome, ctx) {
  const tokens = marked.lexer(lerMd(nome));
  const saida = [];
  for (let i = 0; i < tokens.length; i++) {
    const t = tokens[i];
    const el = elementoComLegenda(t);
    if (el) {
      let j = i + 1;
      while (tokens[j]?.type === "space") j++;
      const leg = tokens[j]?.type === "paragraph" && RE_LEGENDA.test(tokens[j].raw.trim())
        ? separarLegenda(tokens[j].raw) : null;
      if (leg) saida.push(legendaAcima(leg));
      if (el.tipo === "mermaid") saida.push(paragrafoImagem(renderizarMermaid(t.text)));
      else if (el.tipo === "imagem") saida.push(paragrafoImagem(path.join(VAULT, decodeURI(t.tokens[0].href))));
      else saida.push(tabela(t));
      if (leg) {
        saida.push(...legendaAbaixo(leg));
        i = j;
      } else if (el.tipo === "tabela") {
        saida.push(new Paragraph({ style: "Fonte", children: [] }));
      }
      continue;
    }
    saida.push(...bloco(t, ctx));
  }
  return saida;
}

// ---------------------------------------------------------------------------
// Capa e folha de rosto (NBR 14724)
// ---------------------------------------------------------------------------
const centro = (texto, extra = {}) => new Paragraph({
  alignment: AlignmentType.CENTER, spacing: { line: 360, before: 0, after: 0 },
  children: trechos(texto, { bold: true, ...extra }),
});
const vazio = (n) => Array.from({ length: n }, () => new Paragraph({ spacing: { line: 360 }, children: [] }));

const capa = [
  centro(META.instituicao), centro(META.curso), ...vazio(5),
  centro(META.autor), ...vazio(7),
  centro(META.titulo.toUpperCase()), ...vazio(13),
  centro(META.local), centro(META.ano),
  new Paragraph({ children: [new PageBreak()] }),
];

const folhaRosto = [
  centro(META.autor), ...vazio(8),
  centro(META.titulo.toUpperCase()), ...vazio(4),
  new Paragraph({ style: "Natureza", children: trechos(META.natureza, {}) }),
  new Paragraph({ style: "Natureza", spacing: { before: 240 }, children: [
    new TextRun({ text: "Orientador(a): " }), ...trechos(META.orientador, {})] }),
  ...vazio(9),
  centro(META.local), centro(META.ano),
];

const aberturaArtigo = [
  new Paragraph({ style: "TituloArtigo", children: trechos(META.titulo.toUpperCase(), { bold: true }) }),
  new Paragraph({ style: "Autoria", children: [new TextRun({ text: META.autorNome }), new FootnoteReferenceRun(1)] }),
];

// ---------------------------------------------------------------------------
// Estilos (ABNT): Times 12, entrelinha 1,5, recuo de 1,25 cm, títulos numerados
// ---------------------------------------------------------------------------
const simples = { line: 240, before: 0, after: 0 };
const estilos = {
  default: {
    document: { run: { font: FONTE, size: PT(12) }, paragraph: { spacing: { line: 360 } } },
    heading1: { run: { font: FONTE, size: PT(12), bold: true, allCaps: true, color: "000000" },
      paragraph: { spacing: { line: 360, before: 480, after: 240 }, keepNext: true, keepLines: true } },
    heading2: { run: { font: FONTE, size: PT(12), bold: true, color: "000000" },
      paragraph: { spacing: { line: 360, before: 360, after: 240 }, keepNext: true, keepLines: true } },
    heading3: { run: { font: FONTE, size: PT(12), bold: true, italics: true, color: "000000" },
      paragraph: { spacing: { line: 360, before: 240, after: 120 }, keepNext: true, keepLines: true } },
  },
  paragraphStyles: [
    { id: "Corpo", name: "Corpo do texto (ABNT)", basedOn: "Normal", quickFormat: true,
      run: { font: FONTE, size: PT(12) },
      paragraph: { alignment: AlignmentType.JUSTIFIED, indent: { firstLine: Math.round(1.25 * CM) },
        spacing: { line: 360, before: 0, after: 0 } } },
    { id: "TituloSemNumero", name: "Título sem número (ABNT)", basedOn: "Normal", quickFormat: true,
      run: { font: FONTE, size: PT(12), bold: true },
      paragraph: { alignment: AlignmentType.CENTER, keepNext: true, spacing: { line: 360, before: 240, after: 240 } } },
    { id: "TituloArtigo", name: "Título do artigo", basedOn: "Normal",
      run: { font: FONTE, size: PT(12), bold: true },
      paragraph: { alignment: AlignmentType.CENTER, spacing: { line: 360, before: 0, after: 360 } } },
    { id: "Autoria", name: "Autoria", basedOn: "Normal",
      run: { font: FONTE, size: PT(12) },
      paragraph: { alignment: AlignmentType.RIGHT, spacing: { line: 360, before: 0, after: 360 } } },
    { id: "Resumo", name: "Resumo (ABNT)", basedOn: "Normal",
      run: { font: FONTE, size: PT(12) },
      paragraph: { alignment: AlignmentType.JUSTIFIED, spacing: { ...simples, after: 240 } } },
    { id: "PalavrasChave", name: "Palavras-chave", basedOn: "Normal",
      run: { font: FONTE, size: PT(12) },
      paragraph: { alignment: AlignmentType.JUSTIFIED, spacing: { ...simples, after: 480 } } },
    { id: "Natureza", name: "Natureza do trabalho", basedOn: "Normal",
      run: { font: FONTE, size: PT(12) },
      paragraph: { alignment: AlignmentType.JUSTIFIED, indent: { left: Math.round(8 * CM) }, spacing: simples } },
    { id: "Legenda", name: "Legenda (acima)", basedOn: "Normal",
      run: { font: FONTE, size: PT(10) },
      paragraph: { alignment: AlignmentType.CENTER, keepNext: true, spacing: { line: 240, before: 240, after: 120 } } },
    { id: "Fonte", name: "Fonte (abaixo)", basedOn: "Normal",
      run: { font: FONTE, size: PT(10) },
      paragraph: { alignment: AlignmentType.CENTER, spacing: { line: 240, before: 60, after: 240 } } },
    { id: "TextoTabela", name: "Texto de tabela", basedOn: "Normal",
      run: { font: FONTE, size: PT(10) }, paragraph: { spacing: simples } },
    { id: "Codigo", name: "Código", basedOn: "Normal",
      run: { font: MONO, size: PT(9) },
      paragraph: { spacing: simples, indent: { left: 284 },
        shading: { type: ShadingType.CLEAR, color: "auto", fill: "F2F2F2" } } },
    { id: "Citacao", name: "Citação longa (ABNT)", basedOn: "Normal",
      run: { font: FONTE, size: PT(10) },
      paragraph: { alignment: AlignmentType.JUSTIFIED, indent: { left: 4 * CM }, spacing: { ...simples, before: 240, after: 240 } } },
    { id: "Referencia", name: "Referência (ABNT)", basedOn: "Normal",
      run: { font: FONTE, size: PT(12) },
      paragraph: { alignment: AlignmentType.LEFT, spacing: { ...simples, after: 240 } } },
    { id: "ItemLista", name: "Item de lista", basedOn: "Normal",
      run: { font: FONTE, size: PT(12) },
      paragraph: { alignment: AlignmentType.JUSTIFIED, spacing: { line: 360, before: 0, after: 0 } } },
  ],
};

const numeracao = {
  config: [
    { reference: "marcadores", levels: ["•", "◦", "▪"].map((txt, n) => ({
      level: n, format: LevelFormat.BULLET, text: txt, alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 720 + n * 360, hanging: 360 } } } })) },
    { reference: "numeros", levels: [
      { level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 720, hanging: 360 } } } },
      { level: 1, format: LevelFormat.LOWER_LETTER, text: "%2)", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 1080, hanging: 360 } } } },
      { level: 2, format: LevelFormat.LOWER_ROMAN, text: "%3.", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 1440, hanging: 360 } } } },
    ] },
  ],
};

// ---------------------------------------------------------------------------
// Montagem
// ---------------------------------------------------------------------------
const ctx = { secao: "texto" };
const corpo = ARQUIVOS.flatMap((nome) => converterArquivo(nome, ctx));

const margens = { top: 3 * CM, left: 3 * CM, bottom: 2 * CM, right: 2 * CM };
const doc = new Document({
  compatabilityModeVersion: 15,   // Word 2013+: abre sem "Modo de Compatibilidade"
  creator: META.autorNome,
  title: META.titulo,
  description: "Gerado a partir do vault do Obsidian (docs/obsidian-valt) por docs/gerador-docx/gerar.mjs",
  styles: estilos,
  numbering: numeracao,
  footnotes: { 1: { children: [new Paragraph({ style: "Fonte", alignment: AlignmentType.LEFT,
    children: trechos(META.notaAutor, {}) })] } },
  sections: [
    { properties: { page: { margin: margens } }, children: capa },
    // A contagem começa na folha de rosto; o número aparece a partir do texto (NBR 14724)
    { properties: { page: { margin: margens, pageNumbers: { start: 1 } } }, children: folhaRosto },
    {
      properties: { page: { margin: margens, pageNumbers: { start: 2 } } },
      headers: { default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT,
        children: [new TextRun({ children: [PageNumber.CURRENT], size: PT(10) })] })] }) },
      footers: { default: new Footer({ children: [] }) },
      children: [...aberturaArtigo, ...corpo],
    },
  ],
});

// O LibreOffice só importa o somatório (m:nary) com um <m:sup/> explícito, mesmo
// com o limite superior oculto; o Word aceita das duas formas.
const zip = await JSZip.loadAsync(await Packer.toBuffer(doc));
const xml = await zip.file("word/document.xml").async("string");
zip.file("word/document.xml", xml.replace(/<\/m:sub><m:e>/g, "</m:sub><m:sup/><m:e>"));
// A biblioteca grava <w:highlightCs>, que não existe no esquema OOXML: o Word pode
// acusar "conteúdo ilegível" e editores menos tolerantes podem recusar o arquivo.
for (const parte of ["word/document.xml", "word/footnotes.xml", "word/styles.xml", "word/header1.xml"]) {
  const f = zip.file(parte);
  if (f) zip.file(parte, (await f.async("string")).replace(/<w:highlightCs\b[^>]*\/>/g, ""));
}
// Sem entradas de pasta no ZIP (alguns leitores de .docx recusam o arquivo com elas).
// Copia só os arquivos para um pacote novo: no JSZip, remover a pasta apagaria o conteúdo.
const limpo = new JSZip();
const arquivos = [];
zip.forEach((caminho, arq) => { if (!arq.dir) arquivos.push(caminho); });
arquivos.sort((a, b) => (a === "[Content_Types].xml" ? -1 : b === "[Content_Types].xml" ? 1 : 0));
for (const caminho of arquivos) {
  limpo.file(caminho, await zip.file(caminho).async("uint8array"), { createFolders: false });
}
fs.writeFileSync(SAIDA, await limpo.generateAsync({ type: "nodebuffer", compression: "DEFLATE" }));
console.log(`Gerado: ${path.relative(process.cwd(), SAIDA)}`);
console.log("Renumeração de figuras/quadros/tabelas:", renumeracao);
