// Gera as duas versões do artigo (.docx, ABNT) a partir do mesmo vault:
//
//   cd docs/gerador-docx && npm install && npm run gerar
//
// Saídas, com o mesmo texto:
//   docs/DroidServer_TCC_artigo.docx      — versão base do TCC: capa e folha de rosto
//                                           (NBR 14724) seguidas do artigo
//   docs/DroidServer_artigo_topicos.docx  — versão para a Revista Tópicos (NBR 6022), no
//                                           modelo da revista (modelo_artigo.docx): logo no
//                                           cabeçalho da 1ª página, sem capa, seções
//                                           reagrupadas em Introdução, Fundamentação teórica,
//                                           Metodologia, Resultados e discussão e Conclusão
// Nas duas, o artigo abre com título e resumo em português e inglês e autoria com
// nota de minicurrículo. O texto é o mesmo; só mudam a numeração das seções e os
// trechos do vault marcados com %% tcc %% ... %% /tcc %% ou %% topicos %% ... %% /topicos %%.
// Os diagramas Mermaid são renderizados (Chrome do sistema) e guardados em
// docs/obsidian-valt/figuras/diagramas/ — só são refeitos quando o código muda.
// Lacunas ([RESULTADO], [PENDENTE: ...], [DEFINIR: ...]) e referências a conferir (⚠)
// saem destacados em amarelo.

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
const VERSOES = [
  { nome: "base (TCC)", saida: path.resolve(AQUI, "../DroidServer_TCC_artigo.docx"), perfil: "tcc" },
  { nome: "Revista Tópicos", saida: path.resolve(AQUI, "../DroidServer_artigo_topicos.docx"), perfil: "topicos" },
];
const CABECALHO_TOPICOS = path.join(AQUI, "cabecalho-topicos.png");   // logo do modelo da revista
const DIAGRAMAS = path.join(VAULT, "figuras", "diagramas");
const CHROME = process.env.CHROME || "/usr/bin/google-chrome";
const EQUACOES_DIR = path.join(VAULT, "figuras", "equacoes");
// EQUACOES=word gera equação nativa do Word (OMML). O padrão é imagem, que abre
// em qualquer editor (o WordCraft ainda não tem editor de equações).
const EQUACAO_NATIVA = process.env.EQUACOES === "word";

// ---------------------------------------------------------------------------
// Títulos e autoria (o que estiver entre colchetes de PENDENTE/DEFINIR sai destacado)
// ---------------------------------------------------------------------------
const META = {
  // Capa e folha de rosto (só na versão base do TCC)
  instituicao: "CENTRO UNIVERSITÁRIO DO NORTE — UNINORTE",
  curso: "ENGENHARIA DA COMPUTAÇÃO",
  natureza: "Artigo científico apresentado ao curso de Engenharia da Computação do Centro Universitário do " +
    "Norte — Uninorte, como requisito parcial para obtenção do título de Bacharel em Engenharia da Computação.",
  orientador: "Euler de Azevedo Costa",
  local: "MANAUS – AM",
  ano: "2026",
  titulo: "DroidServer: gerenciamento de ambientes Linux do tipo VPS em smartphones Android reaproveitados sem acesso root",
  tituloEn: "DroidServer: managing VPS-like Linux environments on repurposed Android smartphones without root access",
  // Um autor por linha, cada um com a sua nota de rodapé (minicurrículo, NBR 6022).
  // Contribuições (CRediT) ficam na nota 09 do vault.
  autores: [
    { nome: "João Pedro Correia Martins",
      nota: "Graduando em Engenharia da Computação pelo Centro Universitário do Norte — Uninorte, Manaus, AM. " +
        "E-mail: jpedro7682@gmail.com. Endereço postal: Avenida Monsenhor Amancio de Miranda, casa 453, Manaus – AM, CEP 69017-015." },
    { nome: "Euler de Azevedo Costa",
      nota: "Engenheiro SRE (engenharia de confiabilidade de sites) e DevSecOps. Professor do Centro Universitário do Norte — Uninorte, Manaus, AM. " +
        "Orientador do trabalho. E-mail: euller.azevedo@gmail.com." },
  ],
};

// Ordem do artigo (NBR 6022): resumo/abstract, texto, referências, glossário
const ARQUIVOS = [
  "00-resumo.md", "01-introducao.md", "02-referencial-teorico.md", "03-trabalhos-relacionados.md",
  "04-metodologia.md", "05-prototipacao.md", "06-avaliacao-experimental.md", "07-discussao.md",
  "08-conclusao.md", "09-declaracao-ia.md", "10-referencias.md", "11-glossario.md",
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
const DESTAQUE = /(\[RESULTAD[OE][^\]]*\]|\[RESULT[^\]]*\]|⚠|\[PENDENTE[^\]]*\]|\[DEFINIR[^\]]*\])/;

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

// Revista Tópicos: o modelo da revista tem cinco seções. Os capítulos do vault são
// reagrupados (o nível dos títulos desce um degrau) e as remissões "seção N" seguem.
const TOPICOS = {
  secoes: { 3: "2.7", 4: "3", 5: "4.1", 6: "4.2", 7: "4.3", 8: "5" },
  rebaixar: ["03-trabalhos-relacionados.md", "05-prototipacao.md", "06-avaliacao-experimental.md", "07-discussao.md"],
  antes: { "05-prototipacao.md": "# 4. Resultados e Discussão" },
  renomear: { "02-referencial-teorico.md": "Fundamentação Teórica" },   // abrange os trabalhos relacionados
};
const secaoTopicos = (num) => {
  const [cap, ...resto] = num.split(".");
  const novo = TOPICOS.secoes[cap];
  return novo ? [novo, ...resto].join(".") : num;
};

function ajustarTopicos(md, nome) {
  const rebaixar = TOPICOS.rebaixar.includes(nome);
  return md.split("\n").map((linha) => {
    const h = linha.match(/^(#{1,5}) (\d+(?:\.\d+)*)(\.?) (.*)$/);
    if (h) {
      const nomeSecao = h[1].length === 1 && TOPICOS.renomear[nome] ? TOPICOS.renomear[nome] : h[4];
      return `${rebaixar ? "#" : ""}${h[1]} ${secaoTopicos(h[2])}${h[1].length === 1 && !rebaixar ? "." : ""} ${nomeSecao}`;
    }
    return linha.replace(/\b(seç(?:ão|ões)) (\d+(?:\.\d+)*)/g, (_, s, n) => `${s} ${secaoTopicos(n)}`);
  }).join("\n");
}

// Trechos só de uma versão: %% tcc %% ... %% /tcc %% e %% topicos %% ... %% /topicos %%
// (comentários do Obsidian). Os trechos da Tópicos já vêm com a numeração nova.
function versionar(md, nome, perfil) {
  const outro = perfil === "topicos" ? "tcc" : "topicos";
  md = md.replace(new RegExp(`%% ${outro} %%[\\s\\S]*?%% /${outro} %%\\n?`, "g"), "");
  if (perfil !== "topicos") return md.replace(/^%% \/?tcc %%\n?/gm, "");
  const partes = md.split(/(%% topicos %%[\s\S]*?%% \/topicos %%)/);
  md = partes.map((p) => (p.startsWith("%% topicos %%") ? p : ajustarTopicos(p, nome))).join("")
    .replace(/^%% \/?(tcc|topicos) %%\n?/gm, "");
  return TOPICOS.antes[nome] ? `${TOPICOS.antes[nome]}\n\n${md}` : md;
}

function lerMd(nome, perfil = "tcc") {
  return escaparTil(versionar(fs.readFileSync(path.join(VAULT, nome), "utf8"), nome, perfil))
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
  if (!fs.existsSync(caminho)) {  // ex.: capturas de tela ainda não geradas (bench/capturas_tela.py)
    console.warn(`  imagem ausente: ${path.relative(VAULT, caminho)}`);
    return new Paragraph({
      alignment: AlignmentType.CENTER, keepNext: true,
      children: [new TextRun({ text: `[IMAGEM PENDENTE: ${path.basename(caminho)}]`, highlight: "yellow" })],
    });
  }
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

// Legendas vêm cruas do Markdown: itálico e negrito (ex.: *et al.*) passam pelo lexer.
const emLinhaMd = (texto) => emLinha(marked.Lexer.lexInline(texto));
const legendaAcima = (l) => new Paragraph({
  style: "Legenda", keepNext: true,
  children: [new TextRun({ text: `${l.rotulo} — `, bold: true }), ...emLinhaMd(l.titulo)],
});
const legendaAbaixo = (l) => [
  ...(l.nota ? [new Paragraph({ style: "Fonte", children: emLinhaMd(`Nota: ${l.nota}`) })] : []),
  ...(l.lembrete ? [new Paragraph({ style: "Fonte", children: trechos(`[Revisar: ${l.lembrete}]`, { highlight: "yellow" }) })] : []),
  new Paragraph({ style: "Fonte", children: [new TextRun({ text: "Fonte: " }), ...emLinhaMd(l.fonte)] }),
];

// ---------------------------------------------------------------------------
// Blocos
// ---------------------------------------------------------------------------
let instanciaLista = 0;
const NAO_NUMERADAS = ["resumo", "abstract", "contribuição dos autores", "declaração de uso de inteligência artificial", "referências", "glossário"];

// Número do título: "1 Introdução" / "1.1 Contexto" (ABNT, versão do TCC) ou
// "1. INTRODUÇÃO" / "1.1. Contexto" (modelo da Revista Tópicos).
function numerarTitulo(t, topicos) {
  return { ...t, tokens: t.tokens.map((x, i) => (i === 0 && x.type === "text"
    ? { ...x, tokens: undefined, text: x.text.replace(/^(\d+(?:\.\d+)*)\.?\s+/, topicos ? "$1. " : "$1 ") } : x)) };
}

function titulo(t, ctx) {
  const bruto = textoPuro(t.tokens).trim();
  const topicos = ctx.perfil === "topicos";
  if (t.depth === 1) {
    const chave = bruto.toLowerCase().replace(/^\d+\.\s*/, "");
    if (NAO_NUMERADAS.includes(chave)) {
      ctx.secao = chave;
      if (topicos) {   // modelo: RESUMO/ABSTRACT/REFERÊNCIAS BIBLIOGRÁFICAS à esquerda, 14, sem quebra de página
        const texto = chave === "referências" ? "REFERÊNCIAS BIBLIOGRÁFICAS" : chave.toUpperCase();
        return [new Paragraph({ style: ["resumo", "abstract"].includes(chave) ? "TituloResumo" : "TituloSemNumero",
          children: [new TextRun({ text: texto })] })];
      }
      return [new Paragraph({ style: "TituloSemNumero", pageBreakBefore: chave === "referências" || chave === "glossário",
        children: [new TextRun({ text: chave.toUpperCase() })] })];
    }
    ctx.secao = "texto";
    return [new Paragraph({ heading: HeadingLevel.HEADING_1, children: emLinha(numerarTitulo(t, topicos).tokens) })];
  }
  if (ctx.secao === "referências" || ctx.secao === "glossário") {
    return [new Paragraph({ heading: HeadingLevel.HEADING_3, children: emLinha(t.tokens) })];
  }
  return [new Paragraph({ heading: t.depth === 2 ? HeadingLevel.HEADING_2 : HeadingLevel.HEADING_3,
    children: emLinha(numerarTitulo(t, topicos).tokens) })];
}

function estiloParagrafo(ctx) {
  if (["resumo", "abstract"].includes(ctx.secao)) return "Resumo";
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
      if (/^\*\*(Palavras-chave|Keywords|Palabras clave):\*\*/.test(raw)) {
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
  const tokens = marked.lexer(lerMd(nome, ctx.perfil));
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
// Capa e folha de rosto (NBR 14724) — só na versão base do TCC
// ---------------------------------------------------------------------------
const centro = (texto, extra = {}) => new Paragraph({
  alignment: AlignmentType.CENTER, spacing: { line: 360, before: 0, after: 0 },
  children: trechos(texto, { bold: true, ...extra }),
});
const vazio = (n) => Array.from({ length: n }, () => new Paragraph({ spacing: { line: 360 }, children: [] }));
const autorCapa = META.autores[0].nome.toUpperCase();

const capa = () => [
  centro(META.instituicao), centro(META.curso), ...vazio(5),
  centro(autorCapa), ...vazio(7),
  centro(META.titulo.toUpperCase()), ...vazio(11),
  centro(META.local), centro(META.ano),
];

const folhaRosto = () => [
  centro(autorCapa), ...vazio(8),
  centro(META.titulo.toUpperCase()), ...vazio(4),
  new Paragraph({ style: "Natureza", children: trechos(META.natureza, {}) }),
  new Paragraph({ style: "Natureza", spacing: { before: 240 }, children: [
    new TextRun({ text: "Orientador: " }), ...trechos(META.orientador, {})] }),
  ...vazio(7),
  centro(META.local), centro(META.ano),
];

// ---------------------------------------------------------------------------
// Abertura do artigo: títulos em português e inglês (fonte 14) e autoria
// ---------------------------------------------------------------------------
// Modelo da Tópicos: "TÍTULO PRINCIPAL: subtítulo", título em caixa alta (14) e
// subtítulo em 12, os dois em negrito; o título em inglês segue o mesmo formato.
const tituloTopicos = (texto) => {
  const i = texto.indexOf(":");
  const principal = i >= 0 ? texto.slice(0, i + 1) : texto;
  return new Paragraph({ style: "TituloArtigo", children: [
    new TextRun({ text: principal.toUpperCase() + (i >= 0 ? " " : "") }),
    ...(i >= 0 ? trechos(texto.slice(i + 1).trim(), { size: PT(12) }) : []),
  ] });
};

const aberturaArtigo = (perfil) => [
  ...(perfil === "topicos"
    ? [tituloTopicos(META.titulo), tituloTopicos(META.tituloEn)]
    : [new Paragraph({ style: "TituloArtigo", children: trechos(META.titulo, {}) }),
      new Paragraph({ style: "TituloOutraLingua", children: trechos(META.tituloEn, {}) })]),
  ...META.autores.map((a, i) =>
    new Paragraph({ style: "Autoria", spacing: i < META.autores.length - 1 ? { after: 0 } : undefined,
      children: [new TextRun({ text: a.nome }), new FootnoteReferenceRun(i + 1)] })),
];

// ---------------------------------------------------------------------------
// Estilos (ABNT): Times 12, entrelinha 1,5, recuo de 1,25 cm, títulos numerados
// ---------------------------------------------------------------------------
const simples = { line: 240, before: 0, after: 0 };
const estilosTcc = {
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
      run: { font: FONTE, size: PT(14), bold: true },
      paragraph: { alignment: AlignmentType.CENTER, keepNext: true, spacing: { line: 276, before: 0, after: 240 } } },
    { id: "TituloOutraLingua", name: "Título em outra língua", basedOn: "Normal",
      run: { font: FONTE, size: PT(14), bold: true, italics: true },
      paragraph: { alignment: AlignmentType.CENTER, keepNext: true, spacing: { line: 276, before: 0, after: 240 } } },
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

// Modelo da Revista Tópicos (modelo_artigo.docx): títulos de seção 14 em negrito e
// caixa alta, subtítulos 12 em negrito, ambos alinhados à esquerda com entrelinha
// dupla e 12 pt antes; resumo e abstract em espaço simples, sem recuo; nota de
// rodapé em 10, justificada. (Subtítulos com entrelinha 1,5 para não abrir um vão
// duplo logo abaixo do título de seção.) Corpo, legendas, citações e referências como na ABNT.
const ajustesTopicos = {
  heading1: { run: { font: FONTE, size: PT(14), bold: true, allCaps: true, color: "000000" },
    paragraph: { spacing: { line: 480, before: 240, after: 0 }, keepNext: true, keepLines: true } },
  heading2: { run: { font: FONTE, size: PT(12), bold: true, color: "000000" },
    paragraph: { spacing: { line: 360, before: 240, after: 120 }, keepNext: true, keepLines: true } },
  heading3: { run: { font: FONTE, size: PT(12), bold: true, italics: true, color: "000000" },
    paragraph: { spacing: { line: 360, before: 120, after: 60 }, keepNext: true, keepLines: true } },
  estilos: {
    TituloSemNumero: { run: { font: FONTE, size: PT(14), bold: true },
      paragraph: { alignment: AlignmentType.LEFT, keepNext: true, spacing: { line: 480, before: 240, after: 0 } } },
    TituloResumo: { run: { font: FONTE, size: PT(14), bold: true },
      paragraph: { alignment: AlignmentType.LEFT, keepNext: true, spacing: { ...simples, before: 240 } } },
    TituloArtigo: { run: { font: FONTE, size: PT(14), bold: true },
      paragraph: { alignment: AlignmentType.CENTER, keepNext: true, spacing: { ...simples, after: 240 } } },
    Autoria: { run: { font: FONTE, size: PT(12) },
      paragraph: { alignment: AlignmentType.RIGHT, spacing: { ...simples, before: 240, after: 120 } } },
    Resumo: { run: { font: FONTE, size: PT(12) },
      paragraph: { alignment: AlignmentType.JUSTIFIED, spacing: simples } },
    PalavrasChave: { run: { font: FONTE, size: PT(12) },
      paragraph: { alignment: AlignmentType.JUSTIFIED, spacing: { ...simples, after: 240 } } },
    NotaRodape: { run: { font: FONTE, size: PT(10) },
      paragraph: { alignment: AlignmentType.JUSTIFIED, spacing: simples } },
  },
};

function estilos(perfil) {
  const base = { ...estilosTcc, paragraphStyles: [...estilosTcc.paragraphStyles,
    { id: "NotaRodape", name: "Nota de rodapé (autoria)", basedOn: "Normal",
      run: { font: FONTE, size: PT(10) }, paragraph: { alignment: AlignmentType.LEFT, spacing: simples } },
    { id: "TituloResumo", name: "Título do resumo", basedOn: "Normal",
      run: { font: FONTE, size: PT(12), bold: true },
      paragraph: { alignment: AlignmentType.CENTER, keepNext: true, spacing: { line: 360, before: 240, after: 240 } } }] };
  if (perfil !== "topicos") return base;
  return {
    default: { ...base.default, heading1: ajustesTopicos.heading1, heading2: ajustesTopicos.heading2,
      heading3: ajustesTopicos.heading3 },
    paragraphStyles: base.paragraphStyles.map((e) => (ajustesTopicos.estilos[e.id]
      ? { ...e, ...ajustesTopicos.estilos[e.id] } : e)),
  };
}

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
const margens = { top: 3 * CM, left: 3 * CM, bottom: 2 * CM, right: 2 * CM };

const numeroPagina = () => new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT,
  children: [new TextRun({ children: [PageNumber.CURRENT], size: PT(10) })] })] });
const semCabecalho = () => ({ default: new Header({ children: [] }) });

// Modelo da Tópicos: logo da revista no cabeçalho da primeira página e nenhum
// cabeçalho nas demais.
function cabecalhoTopicos() {
  const logo = fs.readFileSync(CABECALHO_TOPICOS);
  return {
    first: new Header({ children: [new Paragraph({ alignment: AlignmentType.CENTER, spacing: simples,
      children: [new ImageRun({ type: "png", data: logo, transformation: { width: 442, height: 173 },
        altText: { name: "Revista Tópicos", title: "Revista Tópicos", description: "Logo da Revista Tópicos" } })] })] }),
    default: new Header({ children: [] }),
  };
}

async function gerar({ saida, perfil }) {
  const comCapa = perfil === "tcc";
  const topicos = perfil === "topicos";
  const corpo = ARQUIVOS.flatMap((nome) => converterArquivo(nome, { secao: "texto", perfil }));
  const artigo = {
    properties: { page: { margin: margens, pageNumbers: { start: comCapa ? 2 : 1 } }, titlePage: topicos },
    headers: topicos ? cabecalhoTopicos() : { default: numeroPagina() },
    footers: { default: new Footer({ children: [] }) },
    children: [...aberturaArtigo(perfil), ...corpo],
  };
  // Na versão base, a contagem começa na folha de rosto (a capa não conta) e o número
  // só aparece a partir do artigo.
  const sections = comCapa ? [
    { properties: { page: { margin: margens } }, headers: semCabecalho(), children: capa() },
    { properties: { page: { margin: margens, pageNumbers: { start: 1 } } }, headers: semCabecalho(), children: folhaRosto() },
    artigo,
  ] : [artigo];
  const doc = new Document({
    compatabilityModeVersion: 15,   // Word 2013+: abre sem "Modo de Compatibilidade"
    creator: META.autores[0].nome,
    lastModifiedBy: META.autores[0].nome,
    title: META.titulo,
    description: "",
    styles: estilos(perfil),
    numbering: numeracao,
    footnotes: Object.fromEntries(META.autores.map((a, i) => [i + 1, { children: [new Paragraph({
      style: "NotaRodape", children: trechos(` ${a.nota}`, {}) })] }])),
    sections,
  });

  // O LibreOffice só importa o somatório (m:nary) com um <m:sup/> explícito, mesmo
  // com o limite superior oculto; o Word aceita das duas formas.
  const zip = await JSZip.loadAsync(await Packer.toBuffer(doc));
  const xml = await zip.file("word/document.xml").async("string");
  zip.file("word/document.xml", xml.replace(/<\/m:sub><m:e>/g, "</m:sub><m:sup/><m:e>"));
  // A biblioteca grava <w:highlightCs>, que não existe no esquema OOXML: o Word pode
  // acusar "conteúdo ilegível" e editores menos tolerantes podem recusar o arquivo.
  for (const parte of Object.keys(zip.files).filter((n) => /^word\/[^/]+\.xml$/.test(n))) {
    zip.file(parte, (await zip.file(parte).async("string")).replace(/<w:highlightCs\b[^>]*\/>/g, ""));
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
  fs.writeFileSync(saida, await limpo.generateAsync({ type: "nodebuffer", compression: "DEFLATE" }));
  console.log(`Gerado: ${path.relative(process.cwd(), saida)}`);
}

// As duas versões saem do mesmo vault; cada uma converte o texto de novo para
// não compartilhar objetos (imagens, notas) entre documentos.
for (const versao of VERSOES) await gerar(versao);
console.log("Renumeração de figuras/quadros/tabelas:", renumeracao);
