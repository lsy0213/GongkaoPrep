// 资料阅读器：资料库里的讲义、笔记、素材整理成的结构化文字。
// 左侧目录（跟随阅读位置高亮），正文分块渲染；选中文字可以高亮、收藏到“我的积累”、问 AI；记录读到哪里。
import { apiGet, apiPost, esc, getAIStatus, store, streamAI, toast } from "./lib.js";
import { mountMindMap } from "./mindmap.js";

const SUBJ_MODULE = { "言语": "言语理解与表达", "数量": "数量关系", "判断": "判断推理", "资料": "资料分析", "常识": "常识判断", "申论": "申论", "面试": "面试" };
const COLORS = [["y", "黄"], ["g", "绿"], ["p", "粉"], ["b", "蓝"]];
const CHUNK = 120;
const AI_PRESETS = ["讲解这段内容", "这在考试里怎么考？举个例子", "帮我提炼要点，方便记忆", "根据这段出 3 道练习题"];

export async function openReader(el, id, startSeq, startFlash) {
  const d = await apiGet("/api/docs/get?id=" + encodeURIComponent(id));
  const blocks = d.blocks; // [seq, kind, level, text, page, data]
  const lexiconDoc = blocks.filter((b) => b[1] === "h" && b[5]?.entry).length >= 30;
  const bySeq = new Map(blocks.map((b) => [b[0], b]));
  const lastSeq = blocks.length ? blocks[blocks.length - 1][0] : 0;
  let marks = d.marks || [];
  const prog = d.progress || {};
  const opened = Date.now();
  let fontSize = store.get("reader-font", 17);
  let panel = null; // "marks" | "ai" | "find"
  let aiSel = null;
  let curSeq = startSeq ?? prog.seq ?? 0;
  let saveTimer = null;
  const cleanups = [];

  // ---------------------------------------------------------------- 渲染
  // 原资料的标题级别常常是平的（“第一节”和“一、”识别成同一级），按编号样式重排层级：
  // 第X章 > 第X节 > 一、 > （一） > 1. > （1）；没有编号的标题跟着前一个标题的相对级别走。正文标题和目录用同一套层级。
  // 资料分析讲义的“第65篇（2023国考）”是一篇材料的编号，排在“一、柱状图类”下面，不是“第一篇”那种大部分
  const H_KINDS = [
    [/^第\s*\d{1,3}\s*篇\s*[（(]/, 3.5],
    [/^第[一二三四五六七八九十百零〇\d]+[章编篇部]/, 0], [/^第[一二三四五六七八九十百零〇\d]+[节课讲]/, 1],
    [/^[一二三四五六七八九十]+[、.．]/, 2], [/^[（(][一二三四五六七八九十]+[）)]/, 3],
    [/^\d{1,2}[、.．](?!\d)/, 4], [/^[（(]\d{1,2}[）)]/, 5],
  ];
  const hKind = (t) => H_KINDS.find(([re]) => re.test((t || "").trim()))?.[1] ?? -1;
  const hDepth = new Map(); // 块号 → 0..3
  {
    const items = new Map();
    const fixed = new Map(); // 整理时已经排好层级的标题（时政晨读·人民日报精读）：照用，不按编号样式重推
    for (const b of blocks) if (b[1] === "h") {
      items.set(b[0], [b[2], b[3]]);
      if (b[5]?.lvfix) fixed.set(b[0], Math.max(0, (b[2] || 1) - 1));
    }
    for (const [lv, t, seq] of d.toc) if (!items.has(seq)) items.set(seq, [lv, t]);
    const seqs = [...items.keys()].sort((a, b) => a - b);
    const kinds = [...new Set(seqs.map((s) => hKind(items.get(s)[1])).filter((k) => k >= 0))].sort((a, b) => a - b);
    // 没编号的标题按原级别排名；只出现一两次的级别（封面大字、宣传语）不占层级，免得正文标题全被挤到最小一级
    const lvCount = {};
    seqs.forEach((s) => { const [lv, t] = items.get(s); if (hKind(t) < 0) lvCount[lv] = (lvCount[lv] || 0) + 1; });
    const nUn = Object.values(lvCount).reduce((a, b) => a + b, 0);
    const lvRank = Object.keys(lvCount).map(Number).filter((lv) => lvCount[lv] >= Math.max(3, nUn * 0.05)).sort((a, b) => a - b);
    const rankOf = (lv) => lvRank.filter((x) => x < lv).length;
    let prev = null;
    for (const s of seqs) {
      const [lv, t] = items.get(s);
      const k = hKind(t);
      const dep = fixed.has(s) ? fixed.get(s)
        : k >= 0 ? kinds.indexOf(k)
        : !prev ? rankOf(lv)
        : lv > prev.lv ? prev.dep + 1 : prev.dep - (prev.lv - lv);
      prev = { lv, dep: Math.max(0, Math.min(3, dep)) };
      hDepth.set(s, prev.dep);
    }
    d.toc = d.toc.map(([, t, seq]) => [hDepth.get(seq), t, seq]);
  }

  // 词条型资料的目录按 20 条折叠，避免侧栏被上百个词条占满。
  let denseToc = false;
  {
    const lvCount = {};
    d.toc.forEach(([lv]) => (lvCount[lv] = (lvCount[lv] || 0) + 1));
    const [topLv, n] = Object.entries(lvCount).sort((a, b) => b[1] - a[1])[0] || [0, 0];
    if (n > 80 && n >= d.toc.length * 0.9) {
      denseToc = true;
      const grouped = [];
      let k = 0;
      for (const t of d.toc) {
        if (+t[0] === +topLv) {
          if (k % 20 === 0) grouped.push([+topLv - 1, `第 ${k + 1}–${Math.min(k + 20, n)} 条`, t[2]]);
          k++;
        }
        grouped.push(t);
      }
      d.toc = grouped;
    }
  }
  const minLv = Math.min(...d.toc.map((t) => t[0]), 9);
  const scannedDoc = d.ext === "pdf" && d.scanned * 2 >= d.pages; // 大半是扫描页才算扫描件
  const quiz = d.quiz || {};

  // 文字里的竖排分数 ⦅分子⁄分母⦆ 和答题横线 ____（填空可以直接输入）
  // 每个答题横线都是输入框：填好按回车对答案（有参考答案的判对错，没有的提示资料没给）
  const BLANK_RE = /[_＿]*_{3,}[_＿]*|＿{2,}/g;
  const MATH_RE = /(\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\))/g;
  function rich(text, blanks) {
    let k = 0;
    return (text || "").split(MATH_RE).map((part) => {
      if (/^\\[[(]/.test(part)) {
        const displayMode = part.startsWith("\\[");
        const tex = part.slice(2, -2);
        try {
          if (window.katex) return window.katex.renderToString(tex, { displayMode, throwOnError: true, trust: false, maxExpand: 1000 });
        } catch { /* 源公式有误时仍显示原文，避免空白 */ }
        return esc(part);
      }
      return esc(part)
        .replace(/⦅([^⁄⦆]*)⁄([^⦆]*)⦆/g, (_m, a, b) => `<span class="frac"><span>${a}</span><span>${b}</span></span>`)
        .replace(BLANK_RE, () => {
          const ans = blanks ? blanks[k] : null;
          k++;
          return `<input class="blank" size="5" autocomplete="off" data-a="${esc(ans || "")}" aria-label="填空">`;
        });
    }).join("");
  }
  // 选择题题干里的空：答案就是正确选项的内容（多个空时选项用逗号隔开，依次对应）
  function stemBlanks(q) {
    const n = ((q.stem || "").match(BLANK_RE) || []).length;
    if (!n || !q.ans || q.ans.length !== 1) return null;
    const opt = plain((q.opts.find(([a]) => a === q.ans) || [])[1] || "").trim();
    if (!opt) return null;
    if (n === 1) return [opt];
    const parts = opt.split(/[，,、；;\s]+/).filter(Boolean);
    return parts.length === n ? parts : null;
  }
  const plain = (t) => (t || "").replace(/⦅([^⁄⦆]*)⁄([^⦆]*)⦆/g, "$1/$2");
  const qkeyOf = (q) => plain(q.stem).replace(/\s+/g, "").slice(0, 40);

  // 多选题（答案不止一个字母，或题干写着多选 / 不定项）：先点选几个，再提交
  const isMulti = (q) => (q.ans || "").length > 1 || /多选|不定项/.test(q.stem || "");

  const KEYS_TIP = (multi) => `<span class="q-keys">${multi ? "可以选多个，" : ""}点选项或按 <kbd>A</kbd>–<kbd>D</kbd> 选择，<kbd>Enter</kbd> 确认并看答案</span>`;

  // 插图（统计图、题目里的图）：按原资料里的大小显示，点开放大看清数字
  function figHTML(f, cls, attrs = "") {
    if (!f?.src) return "";
    const w = f.pw ? Math.round(f.pw * 1.75) : f.w ? Math.round(f.w / 2) : 0;
    return `<figure class="${cls}"${attrs}><img src="/api/docimg/${esc(f.src)}?v=${f.w || 0}x${f.h || 0}" alt="${f.chart ? "统计图" : "插图"}" loading="lazy" decoding="async"
      ${f.w && f.h ? `width="${f.w}" height="${f.h}"` : ""}${w ? ` style="width:min(100%, ${w}px)"` : ""} data-zoom></figure>`;
  }

  function qHTML(seq, page, q) {
    const multi = isMulti(q);
    const picks = q.opts.map(([a, o]) => `<button class="q-opt" data-o="${a}"><b>${a}</b>${o ? `<span>${rich(o)}</span>` : ""}</button>`).join("");
    // 题里的文字表格、材料图、画在图里的选项
    const figs = (q.figs || []).map((f) => f.rows ? `<div class="table-wrap"><table class="rd-tbl">${f.rows.map((r, i) => `<tr>${r.map((c) => (i ? `<td>${esc(c)}</td>` : `<th>${esc(c)}</th>`)).join("")}</tr>`).join("")}</table></div>`
      : figHTML(f, "q-fig")).join("");
    return `<div class="rd-q${multi ? " multi" : ""}" data-seq="${seq}" data-pg="${page}" data-q="${seq}">
      <div class="q-stem">${multi ? `<span class="chip warn">多选</span> ` : ""}${rich(q.stem, stemBlanks(q)).replace(/\n/g, "<br>")}</div>${figs}
      <div class="q-opts${q.opts.every(([, o]) => !o) ? " letters" : ""}">${picks}</div>
      <div class="q-foot"><span class="q-res">${KEYS_TIP(multi)}</span><span class="spacer"></span>
        <button class="btn sm primary" data-qa="submit">确定</button>
        <button class="btn sm ghost" data-qa="show">${q.ans ? "看答案" : "答案"}</button><button class="btn sm ghost" data-qa="ai">问 AI</button>
        <button class="btn sm ghost" data-qa="redo" hidden>重做</button></div>
      <div class="q-exp" hidden></div></div>`;
  }

  function treeNodes(items) {
    const roots = [];
    const stack = [];
    for (const [rawDepth, title] of items) {
      const depth = Math.max(0, Number(rawDepth) || 0);
      while (stack.length && stack[stack.length - 1].depth >= depth) stack.pop();
      const node = { title, depth, children: [] };
      (stack.length ? stack[stack.length - 1].children : roots).push(node);
      stack.push(node);
    }
    return roots;
  }

  function outlineNodes(nodes, depth = 0) {
    return nodes.map((node) => {
      const children = node.children;
      const shortLeaves = children.length > 1 && children.length <= 8 &&
        children.every((x) => !x.children.length && x.title.length <= 24 && !/[。！？]$/.test(x.title));
      const inner = shortLeaves
        ? `<div class="rd-outline-children${depth >= 2 ? " deep" : ""} rd-outline-inline">${children.map((x) => `<span>${rich(x.title)}</span>`).join("")}</div>`
        : children.length ? `<div class="rd-outline-children${depth >= 2 ? " deep" : ""}">${outlineNodes(children, depth + 1)}</div>` : "";
      return `<div class="rd-outline-item"><div class="rd-outline-text${children.length ? " branch" : ""}${depth === 0 ? " root" : ""}${depth >= 3 ? " fine" : ""}">${rich(node.title)}</div>${inner}</div>`;
    }).join("");
  }

  let treeView = store.get("reader-tree-view", "map");

  // 标题里的“第一节透镜”：编号和标题之间留出空隙（只加标签不改文字，标注位置不受影响）
  const HNO_RE = /^(第[一二三四五六七八九十百零〇\d]+(?:章|节|编|篇|部分|课|讲|单元))(\s*)(?=[^\s：:、，,.．）)])/;
  function headHTML(text) {
    const m = (text || "").match(HNO_RE);
    return m ? `<span class="h-no${m[2] ? "" : " gap"}">${esc(m[0])}</span>${rich(text.slice(m[0].length))}` : rich(text);
  }

  // 段落：编号条目悬挂缩进，按编号样式分层（“1.”下面的“（1）”“①”往里缩一级，对齐上一级的正文）；
  // 条目以冒号结尾时，后面不带编号的段落算它的内容。段首“种类：”“【适用】”这类小标签加粗。
  const P_KINDS = [
    [/^[一二三四五六七八九十]+[、.．]/, 0], [/^[（(][一二三四五六七八九十]+[）)]/, 1],
    [/^\d{1,3}[、.．](?![\d%％])/, 2], [/^[⒈-⒛]/, 2], [/^[（(]\d{1,2}[）)]/, 3],
    [/^[①-⑳]/, 4], [/^[•●▪■◆◇★☆√·]/, 5],
  ];
  const LABEL_RE = /^(?:【[^】\n]{1,16}】|〖[^〗\n]{1,8}〗|[^，,。；;：:！？!?“”"‘’《》()（）\s_\\=+＋×÷/【】]{1,12}[：:](?!\/))/;
  // 编号所占宽度（em）：半角数字和标点窄，其余按一个字宽；再留一点空隙
  const markW = (s) => {
    let w = 0;
    for (const ch of s) w += /\d/.test(ch) ? 0.6 : /[.()]/.test(ch) ? 0.35 : 1;
    return Math.round((w + (/[.()\d]$/.test(s) ? 0.3 : 0.1)) * 20) / 20;
  };
  const nextOf = new Map(blocks.map((b, i) => [b[0], blocks[i + 1]]));
  let list = [];     // 当前条目层级：[{rank, end}]，end = 该条正文的起点（em）
  let cont = null;   // 冒号结尾的条目正文起点：后面不带编号的段落缩进到这里
  let open = null;   // 上一段没说完（PDF 在句子中间断了行）：它正文的起点，下一段紧贴着接上
  const endList = () => { list = []; cont = null; open = null; };
  const OPEN_END_RE = /[。！？；：:…”’」』）)】!?;.]\s*$/;

  function paraHTML(seq, page, text, data, style) {
    const t = text || "";
    let cls = style, css = "", head = "", rest = t, indent = 0;
    const plainPara = !data?.side && !data?.b;
    const pk = !plainPara || lexiconDoc ? null : P_KINDS.find(([re]) => re.test(t));
    const lm0 = plainPara && !pk ? t.match(LABEL_RE) : null;
    if (pk) {
      const mk = t.match(pk[0])[0] + (t.slice(t.match(pk[0])[0].length).match(/^\s*/)[0]);
      while (list.length && list[list.length - 1].rank >= pk[1]) list.pop();
      const base = list.length ? list[list.length - 1].end : 0;
      const w = markW(mk.trim());
      list.push({ rank: pk[1], end: base + w });
      cont = /[：:]\s*$/.test(t) ? base + w : null;
      indent = base + w;
      cls += " li";
      css = `--in:${indent}em;--m:${w}em`;
      head = `<span class="li-m">${esc(mk)}</span>`;
      rest = t.slice(mk.length);
    } else if (open != null && plainPara && !lm0) {
      indent = open;
      cls += indent ? " rd-join li-c" : " rd-join";
      if (indent) css = `--in:${indent}em`;
    } else if (cont != null && plainPara) {
      indent = cont;
      cls += " li-c";
      css = `--in:${indent}em`;
    } else endList();
    const lm = plainPara ? rest.match(LABEL_RE) : null;
    if (lm && !/^\s*[“"‘「]/.test(rest.slice(lm[0].length))) {
      if (!rest.slice(lm[0].length).trim()) cls += " rd-lead";
      else {
        head += `<b class="lbl${lm[0].startsWith("【") || lm[0].startsWith("〖") ? " brk" : ""}">${rich(lm[0])}</b>`;
        rest = rest.slice(lm[0].length);
      }
    }
    // 单独一行的短编号小标题（“3. 川菜”），下面跟着成段的正文：当小标题加粗
    if (pk && !/rd-lead/.test(cls) && !lm && rest.trim().length <= 14 && !/[，,。；;！？!?]/.test(rest)) {
      const nx = nextOf.get(seq);
      if (nx && nx[1] === "p" && (nx[3] || "").length >= 30 && !P_KINDS.some(([re]) => re.test(nx[3]))) cls += " rd-lead";
    }
    open = plainPara && !/rd-lead/.test(cls) && t.trim().length >= 12 && !OPEN_END_RE.test(t) ? indent : null;
    cls = cls.trim();
    return `<p data-seq="${seq}" data-pg="${page}"${cls ? ` class="${cls}"` : ""}${css ? ` style="${css}"` : ""}>${head}${rich(rest, data?.blanks)}</p>`;
  }

  // 图题：统计图下面紧跟着的一行短字（“图2 2021年我国……进口量”“（单位：亿元）”）
  const prevOf = new Map(blocks.map((b, i) => [b[0], blocks[i - 1]]));
  const CAP_RE = /^(?:图\s*\d|表\s*\d|[（(]?\s*单位|资料来源|数据来源|注[：:])|(?:情况|构成|统计|变化|对比|分布|趋势|示意图|结构)(?:[（(][^）)]*[）)])?\s*$/;
  function isCaption(b) {
    const prev = prevOf.get(b[0]);
    const t = (b[1] === "box" ? (b[5]?.lines || []).map(([x]) => x).join(" ") : b[3] || "").trim();
    return prev?.[1] === "img" && t.length <= 60 && !t.includes("\n") && !/[。？?：:]$/.test(t) && (b[1] === "box" ? (b[5]?.lines || []).length <= 2 : true)
      && (CAP_RE.test(t) || (t.length <= 30 && !/^(?:\d{1,3}\s*[.．、]|[A-H]\s*[.．、]|[一二三四五六七八九十]+、|[（(]|第)/.test(t)));
  }

  function blockHTML(b) {
    const [seq, kind, lv, text, page, data] = b;
    if (kind !== "p") endList();
    if (kind === "h") {
      const dep = hDepth.get(seq) ?? 0;
      return `<h${dep + 2} class="rd-h${data?.entry ? " rd-entry" : ""}" data-seq="${seq}" data-pg="${page}">${headHTML(text)}</h${dep + 2}>`;
    }
    if (kind === "p" && isCaption(b)) return `<p class="rd-cap" data-seq="${seq}" data-pg="${page}">${rich(text)}</p>`;
    if (kind === "p") {
      let style = data?.side ? "rd-side" : data?.b ? "rd-b" : "";
      if (lexiconDoc) {
        if (/^考频[:：]/.test(text)) style += " rd-lex-meta";
        else if (/^(易混淆成语|区分)$/.test(text)) style += " rd-lex-label";
        else if (/^[^。；]{2,24}\s*VS\s*[^。；]{2,24}$/i.test(text)) style += " rd-lex-compare";
        else if (/^例句[:：]/.test(text)) style += " rd-lex-example";
      }
      return paraHTML(seq, page, text, data, style);
    }
    if (kind === "tree") {
      const nodes = treeNodes(data?.items || []);
      const map = treeView === "map";
      return `<section class="rd-tree" data-seq="${seq}" data-pg="${page}">
        <div class="rd-tree-tools"><span>思维导图</span><span class="seg"><button type="button" data-tree-view="map"${map ? ' class="on"' : ""}>导图</button><button type="button" data-tree-view="outline"${map ? "" : ' class="on"'}>文字提纲</button></span></div>
        <div class="rd-outline"${map ? " hidden" : ""}>${outlineNodes(nodes)}</div>
        <div class="rd-map"${map ? "" : " hidden"}></div>
      </section>`;
    }
    if (kind === "q" && data) return qHTML(seq, page, data);
    if (kind === "box" && isCaption(b)) {
      return `<p class="rd-cap" data-seq="${seq}" data-pg="${page}">${rich((data?.lines || []).map(([t]) => t).join(" ") || text)}</p>`;
    }
    if (kind === "box") {
      return `<div class="rd-box" data-seq="${seq}" data-pg="${page}">${(data?.lines || []).map(([t, a]) =>
        `<div class="${a === "c" ? "c" : a === "r" ? "r" : ""}"${typeof a === "number" && a ? ` style="padding-left:${a * 2}em"` : ""}>${rich(t)}</div>`).join("")}</div>`;
    }
    if (kind === "tbl") {
      const rows = data?.rows || [];
      return `<div class="table-wrap" data-seq="${seq}" data-pg="${page}"><table class="rd-tbl">${rows.map((r, i) =>
        `<tr>${r.map((c) => (i === 0 ? `<th>${esc(c)}</th>` : `<td>${esc(c)}</td>`)).join("")}</tr>`).join("")}</table></div>`;
    }
    if (kind === "img") return figHTML(data, "rd-fig", ` data-seq="${seq}" data-pg="${page}"`);
    return "";
  }

  function bodyHTML() {
    let html = "";
    endList();
    for (let i = 0; i < blocks.length; i += CHUNK) {
      html += `<div class="rd-chunk">`;
      for (const b of blocks.slice(i, i + CHUNK)) html += blockHTML(b);
      html += `</div>`;
    }
    return html || `<div class="empty"><h3>这份资料没有识别出文字</h3><p>${esc(d.error || "可能是几乎没有文字的图片文件。")}</p></div>`;
  }

  function tocHTML() {
    if (!d.toc.length) {
      // 没有目录：按页给出跳转
      if (d.pages > 3) {
        const pages = [...new Set(blocks.map((b) => b[4]))];
        const step = Math.max(1, Math.round(pages.length / 25));
        return `<div class="small muted mb">这份资料没有识别出标题，按页跳转：</div>` +
          pages.filter((_p, i) => i % step === 0).map((p) => {
            const b = blocks.find((x) => x[4] === p);
            return `<button class="toc-i" data-go="${b[0]}" style="padding-left:6px">第 ${p + 1} 页</button>`;
          }).join("");
      }
      return `<div class="small muted">这份资料没有目录</div>`;
    }
    return d.toc.map(([lv, t, seq], i) => {
      const depth = lv - minLv;
      const next = d.toc[i + 1];
      const parent = next && next[0] > lv;
      return `<button class="toc-i" data-go="${seq}" data-i="${i}" data-depth="${depth}" style="padding-left:${6 + depth * 14}px"
        ${(denseToc ? depth > 0 : depth > 1) ? "hidden" : ""}>${parent ? `<span class="caret" data-fold="${i}">▸</span>` : `<span class="caret"></span>`}${esc(t)}</button>`;
    }).join("");
  }

  const pct = () => (lastSeq ? Math.round((curSeq / lastSeq) * 100) : 100);
  const nQ = blocks.filter((b) => b[1] === "q").length;

  el.innerHTML = `
    <div class="rd">
      <div class="rd-bar">
        <a class="btn sm ghost" href="${esc(d.back?.href || "#/library")}">← ${esc(d.back?.label || "资料库")}</a>
        <div class="rd-title"><b title="${esc(d.rel)}">${esc(d.title)}</b>
          <span class="small muted">${d.chars > 10000 ? `约 ${(d.chars / 10000).toFixed(1)} 万字` : `${d.chars} 字`}${scannedDoc ? " · 扫描件已识别文字" : ""}${nQ ? ` · 例题 ${nQ} 道，选好按 Enter 看答案` : ""} · <span id="pct">已读 ${pct()}%</span></span></div>
        <span class="spacer"></span>
        <form id="findf" class="rd-find"><input type="search" id="findq" placeholder="在本资料中查找" autocomplete="off"></form>
        <div class="seg"><button id="fminus" title="字号减小">A−</button><button id="fplus" title="字号增大">A+</button></div>
        <button class="btn sm ghost" id="tocbtn" title="显示 / 隐藏目录">目录</button>
        <button class="btn sm ghost" id="marksbtn">标注 <span id="mcount">${marks.length}</span></button>
        <button class="btn sm ghost" id="aibtn">问 AI</button>
        <button class="btn sm ghost" id="fav">${prog.fav ? "★ 已收藏" : "☆ 收藏"}</button>
        <button class="btn sm ghost" id="done">${prog.done ? "✓ 已读完" : "标记读完"}</button>
      </div>
      <div class="rd-body ${store.get("reader-toc", true) ? "" : "no-toc"}">
        <aside class="rd-toc" id="toc">${tocHTML()}</aside>
        <article class="rd-doc" id="doc" style="font-size:${fontSize}px">${bodyHTML()}</article>
        <aside class="rd-panel" id="panel" hidden></aside>
      </div>
      <div class="rd-tools" id="seltools" hidden>
        <div class="rd-tools-row">
          ${COLORS.map(([c, n]) => `<button class="dot hl-${c}" data-hl="${c}" title="${n}色高亮（再点一次取消）"></button>`).join("")}
          <button data-act="unhl" title="去掉选中文字上的高亮" hidden>✕ 取消高亮</button>
          <span class="sep"></span>
          <button data-act="note">摘到积累</button><button data-act="ai">问 AI</button><button data-act="copy">复制</button>
        </div>
        <div class="rd-tools-row rd-books" id="bookrow"></div>
      </div>
      <div class="rd-pop" id="markpop" hidden></div>
    </div>`;

  const doc = el.querySelector("#doc");
  const tocEl = el.querySelector("#toc");
  const panelEl = el.querySelector("#panel");
  const tools = el.querySelector("#seltools");
  const pop = el.querySelector("#markpop");

  // ---------------------------------------------------------------- 高亮
  function textNodes(node) {
    const out = [];
    const content = node.matches?.(".rd-tree") ? node.querySelector(".rd-outline") : node;
    const w = document.createTreeWalker(content, NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => (n.parentElement.closest("details summary, .rd-page, .katex-mathml") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
    });
    while (w.nextNode()) out.push(w.currentNode);
    return out;
  }

  function wrapRange(blockEl, start, end, m) {
    let pos = 0;
    for (const tn of textNodes(blockEl)) {
      const len = tn.data.length;
      const a = Math.max(start, pos), z = Math.min(end, pos + len);
      if (a < z) {
        const r = document.createRange();
        r.setStart(tn, a - pos);
        r.setEnd(tn, z - pos);
        const mk = document.createElement("mark");
        mk.className = `hl hl-${m.color || "y"}${m.note ? " has-note" : ""}`;
        mk.dataset.mid = m.id;
        if (m.note) mk.title = m.note;
        r.surroundContents(mk);
      }
      pos += len;
      if (pos >= end) break;
    }
  }

  function applyMark(m) {
    for (let s = m.seq; s <= m.end_seq; s++) {
      const be = doc.querySelector(`[data-seq="${s}"]`);
      if (!be) continue;
      const len = textNodes(be).reduce((a, t) => a + t.data.length, 0);
      wrapRange(be, s === m.seq ? m.start : 0, s === m.end_seq ? m.end : len, m);
    }
  }

  function unwrapMark(id) {
    doc.querySelectorAll(`mark[data-mid="${id}"]`).forEach((mk) => {
      const parent = mk.parentNode;
      while (mk.firstChild) parent.insertBefore(mk.firstChild, mk);
      parent.removeChild(mk);
      parent.normalize();
    });
  }

  // 资料重新整理后块号会变：标注先核对原位置的文字，对不上就按标注的文字重新找位置
  const domText = (s) => {
    const be = doc.querySelector(`[data-seq="${s}"]`);
    return be ? textNodes(be).map((t) => t.data).join("") : "";
  };
  const squash = (t) => t.replace(/\s+/g, "");

  function anchored(m) {
    const a = domText(m.seq);
    if (m.seq === m.end_seq) return squash(a.slice(m.start, m.end)) === squash(m.text);
    return squash(m.text).startsWith(squash(a.slice(m.start))) && squash(a.slice(m.start)).length > 0;
  }

  function relocate(m) {
    const near = blocks.map((b) => b[0]).sort((x, y) => Math.abs(x - m.seq) - Math.abs(y - m.seq));
    const parts = m.text.split(/\n+/).map((t) => t.trim()).filter(Boolean);
    for (const s of near) {
      const t = domText(s);
      if (parts.length <= 1) {
        const i = t.indexOf(m.text.trim());
        if (i >= 0) return { seq: s, start: i, end_seq: s, end: i + m.text.trim().length };
        continue;
      }
      const i = t.lastIndexOf(parts[0]);
      if (i < 0) continue;
      const last = parts[parts.length - 1];
      for (let e = s + 1; e <= s + parts.length + 2; e++) {
        const j = domText(e).indexOf(last);
        if (j >= 0) return { seq: s, start: i, end_seq: e, end: j + last.length };
      }
    }
    return null;
  }

  for (const m of marks) {
    if (!anchored(m)) {
      const pos = relocate(m);
      if (!pos) { m.lost = true; continue; }
      Object.assign(m, pos);
      apiPost("/api/docmarks", { id: m.id, ...pos }).catch(() => {});
    }
    applyMark(m);
  }

  // 选区 → (块号, 块内偏移)
  function locate(node, offset) {
    const be = (node.nodeType === 1 ? node : node.parentElement).closest("[data-seq]");
    if (!be || !doc.contains(be)) return null;
    const content = be.matches(".rd-tree") ? be.querySelector(".rd-outline") : be;
    if (!content.contains(node)) return null;
    const r = document.createRange();
    r.setStart(content, 0);
    try { r.setEnd(node, offset); } catch { return null; }
    const frag = r.cloneContents();
    frag.querySelectorAll("details summary, .rd-page, .katex-mathml").forEach((x) => x.remove());
    return { seq: +be.dataset.seq, off: frag.textContent.length };
  }

  function currentSelection() {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) return null;
    const range = sel.getRangeAt(0);
    if (!doc.contains(range.commonAncestorContainer)) return null;
    const a = locate(range.startContainer, range.startOffset);
    const z = locate(range.endContainer, range.endOffset);
    const text = sel.toString().trim();
    if (!a || !z || !text) return null;
    return { seq: a.seq, start: a.off, end_seq: z.seq, end: z.off, text, rect: range.getBoundingClientRect(), range: range.cloneRange() };
  }

  // 选中内容的“原文”：公式还原成 \( \) 写法、竖排分数还原成 ⦅⁄⦆，记到本子里才能照样显示公式
  function sourceText(range) {
    const r = range.cloneRange();
    const kOf = (n) => (n.nodeType === 1 ? n : n.parentElement)?.closest(".katex-display, .katex");
    const ka = kOf(r.startContainer), kz = kOf(r.endContainer);
    if (ka) r.setStartBefore(ka);
    if (kz) r.setEndAfter(kz);
    const frag = r.cloneContents();
    if (!frag.querySelector(".katex, .frac")) return null;
    frag.querySelectorAll("details summary, .rd-page, .q-keys").forEach((x) => x.remove());
    frag.querySelectorAll(".katex").forEach((k) => {
      const tex = k.querySelector('annotation[encoding="application/x-tex"]')?.textContent;
      const disp = k.parentElement?.closest(".katex-display");
      (disp || k).replaceWith(tex == null ? k.querySelector(".katex-html")?.textContent || "" : disp ? `\\[${tex}\\]` : `\\(${tex}\\)`);
    });
    frag.querySelectorAll(".frac").forEach((f) => f.replaceWith(`⦅${f.children[0]?.textContent || ""}⁄${f.children[1]?.textContent || ""}⦆`));
    frag.querySelectorAll("input.blank").forEach((x) => x.replaceWith("____"));
    frag.querySelectorAll("br").forEach((x) => x.replaceWith("\n"));
    frag.querySelectorAll("[data-seq], p, li, tr, .q-opt, .rd-box > div").forEach((x) => x.append("\n"));
    return frag.textContent.replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
  }

  function sectionOf(seq) {
    let t = "";
    for (const [, title, s] of d.toc) { if (s <= seq) t = title; else break; }
    return t;
  }

  function contextOf(seq) {
    const out = [];
    for (let s = seq - 3; s <= seq + 3; s++) {
      const b = bySeq.get(s);
      if (b && b[3] && b[1] !== "img") out.push(b[3]);
    }
    return out.join("\n");
  }

  let sel = null;
  // 选区碰到的已有高亮（按块号 + 块内偏移比较位置）
  const before = (s1, o1, s2, o2) => s1 < s2 || (s1 === s2 && o1 < o2);
  const marksIn = (s) => marks.filter((m) => !m.lost && before(m.seq, m.start, s.end_seq, s.end) && before(s.seq, s.start, m.end_seq, m.end));

  // 工具条上的高亮状态：已经高亮的颜色点亮，出现“取消高亮”
  function paintHl() {
    const hits = sel?.hits || [];
    tools.querySelectorAll("[data-hl]").forEach((b) => b.classList.toggle("on", hits.some((m) => m.color === b.dataset.hl)));
    tools.querySelector('[data-act="unhl"]').hidden = !hits.length;
  }

  function showTools() {
    sel = currentSelection();
    if (!sel) { tools.hidden = true; return; }
    sel.hits = marksIn(sel);
    paintHl();
    tools.hidden = false;
    const r = sel.rect, h = tools.offsetHeight;
    const top = r.top - h - 8 < 60 ? r.bottom + 8 : r.top - h - 8;
    tools.style.top = top + "px";
    tools.style.left = Math.max(8, Math.min(window.innerWidth - tools.offsetWidth - 8, r.left + r.width / 2 - tools.offsetWidth / 2)) + "px";
  }

  const onMouseUp = (e) => {
    if (tools.contains(e.target) || pop.contains(e.target)) return;
    setTimeout(showTools, 10);
  };
  doc.addEventListener("mouseup", onMouseUp);
  const onDocDown = (e) => {
    if (!tools.contains(e.target)) tools.hidden = true;
    if (!pop.contains(e.target) && !e.target.closest?.("mark.hl")) pop.hidden = true;
  };
  document.addEventListener("mousedown", onDocDown);
  cleanups.push(() => document.removeEventListener("mousedown", onDocDown));

  // 导图在显示出来、滚到附近时才排版（隐藏时量不出节点大小）
  const mapStops = [];
  function mountMap(tree) {
    const host = tree.querySelector(".rd-map");
    if (host.hidden || host.dataset.on) return;
    host.dataset.on = "1";
    const b = bySeq.get(+tree.dataset.seq);
    const items = b?.[5]?.items || [];
    const prev = blocks[blocks.indexOf(b) - 1];
    const title = prev && prev[1] === "h" && !/^思维导图$/.test(prev[3].trim()) ? prev[3] : d.title;
    mapStops.push(mountMindMap(host, treeNodes(items), { title }));
  }
  const mapIO = new IntersectionObserver((ents) => ents.forEach((x) => x.isIntersecting && mountMap(x.target)), { root: doc, rootMargin: "400px 0px" });
  doc.querySelectorAll(".rd-tree").forEach((t) => mapIO.observe(t));
  cleanups.push(() => { mapIO.disconnect(); mapStops.forEach((f) => f()); });

  function showTreeView(tree, view) {
    const showMap = view === "map";
    tree.querySelector(".rd-outline").hidden = showMap;
    tree.querySelector(".rd-map").hidden = !showMap;
    tree.querySelectorAll("[data-tree-view]").forEach((x) => x.classList.toggle("on", x.dataset.treeView === view));
    if (showMap) mountMap(tree);
  }

  // 点统计图放大看（按原图分辨率显示，可滚动）；Esc 或点空白处关闭
  doc.addEventListener("click", (e) => {
    const img = e.target.closest("img[data-zoom]");
    if (!img) return;
    const ov = document.createElement("div");
    ov.className = "rd-overlay rd-zoom";
    ov.innerHTML = `<figure><img src="${img.getAttribute("src")}" alt=""><figcaption class="small muted">点空白处或按 Esc 关闭</figcaption></figure>`;
    const close = () => { ov.remove(); document.removeEventListener("keydown", onKey, true); };
    const onKey = (ev) => { if (ev.key === "Escape") { ev.stopPropagation(); close(); } };
    ov.onclick = (ev) => { if (ev.target === ov || ev.target.tagName === "FIGCAPTION") close(); };
    document.addEventListener("keydown", onKey, true);
    document.body.appendChild(ov);
  });

  doc.addEventListener("click", (e) => {
    const view = e.target.closest(".rd-tree [data-tree-view]");
    if (!view) return;
    treeView = view.dataset.treeView;
    store.set("reader-tree-view", treeView);
    showTreeView(view.closest(".rd-tree"), treeView);
  });

  async function dropMarks(list) {
    for (const m of list) {
      await apiPost("/api/docmarks/delete", { id: m.id });
      unwrapMark(m.id);
    }
    const ids = new Set(list.map((m) => m.id));
    marks = marks.filter((x) => !ids.has(x.id));
    el.querySelector("#mcount").textContent = marks.length;
    if (panel === "marks") drawPanel();
  }

  async function recolor(m, color) {
    m.color = color;
    await apiPost("/api/docmarks", { id: m.id, color: m.color, note: m.note });
    unwrapMark(m.id);
    applyMark(m);
    if (panel === "marks") drawPanel();
  }

  // 点颜色：没高亮过就高亮；已经是这个颜色就取消；是别的颜色就换色。
  // 高亮完工具条先不收起，点错了可以马上再点一次取消
  tools.querySelectorAll("[data-hl]").forEach((b) => (b.onclick = async () => {
    if (!sel) return;
    const color = b.dataset.hl;
    try {
      if (sel.hits.length) {
        if (sel.hits.every((m) => m.color === color)) {
          await dropMarks(sel.hits);
          sel.hits = [];
        } else {
          for (const m of sel.hits) await recolor(m, color);
        }
        paintHl();
        return;
      }
      const m = { doc: d.id, seq: sel.seq, start: sel.start, end_seq: sel.end_seq, end: sel.end, text: sel.text, color, note: "" };
      const r = await apiPost("/api/docmarks", m);
      m.id = r.id;
      marks.push(m);
      window.getSelection().removeAllRanges();
      applyMark(m);
      sel.hits = [m];
      paintHl();
      el.querySelector("#mcount").textContent = marks.length;
      if (panel === "marks") drawPanel();
    } catch (e) { toast(e.message); }
  }));
  tools.querySelector('[data-act="unhl"]').onclick = async () => {
    if (!sel?.hits.length) return;
    try {
      await dropMarks(sel.hits);
      sel.hits = [];
      paintHl();
      toast("已取消高亮");
    } catch (e) { toast(e.message); }
  };
  tools.querySelector('[data-act="copy"]').onclick = async () => {
    if (!sel) return;
    try { await navigator.clipboard.writeText(sel.text); toast("已复制"); } catch { document.execCommand("copy"); }
    tools.hidden = true;
  };
  tools.querySelector('[data-act="note"]').onclick = async () => {
    if (!sel) return;
    try {
      await apiPost("/api/notebook", { kind: "摘抄", title: sectionOf(sel.seq) || d.title, content: sel.text, source: d.title });
      toast("已摘到“素材积累 → 我的积累”，也会出现在闪卡里");
    } catch (e) { toast(e.message); }
    tools.hidden = true;
  };

  // 笔记本：工具条第二行列出所有笔记本，点哪个就直接记进哪个；“＋”当场新建一个并记进去
  const bookRow = tools.querySelector("#bookrow");
  let books = [];
  function drawBooks() {
    bookRow.innerHTML = `<span class="rd-tools-lab">记到</span>${books.map((b) => `<button data-book="${b.id}">${esc(b.name)}</button>`).join("")}
      <button data-newbook title="新建笔记本">＋ 新建</button>`;
    bookRow.querySelectorAll("[data-book]").forEach((x) => (x.onclick = () => saveTo(books.find((b) => b.id === +x.dataset.book))));
    bookRow.querySelector("[data-newbook]").onclick = (e) => {
      const box = document.createElement("input");
      box.placeholder = "笔记本名字，回车";
      box.className = "rd-newbook";
      e.currentTarget.replaceWith(box);
      box.focus();
      box.onkeydown = async (ev) => {
        if (ev.key === "Escape") { drawBooks(); return; }
        if (ev.key !== "Enter" || !box.value.trim()) return;
        try {
          const { id } = await apiPost("/api/memo/book", { name: box.value.trim() });
          await loadBooks();
          saveTo(books.find((b) => b.id === id));
        } catch (err) { toast(err.message); }
      };
    };
  }
  async function loadBooks() {
    try { books = (await apiGet("/api/memo/books")).books; } catch { books = []; }
    drawBooks();
  }
  async function saveTo(book) {
    if (!sel || !book) return;
    try {
      const r = await apiPost("/api/memo", {
        book: book.id, content: sourceText(sel.range) || sel.text,
        source: [d.title, sectionOf(sel.seq)].filter(Boolean).join(" · "), doc: d.id, seq: sel.seq,
      });
      toast(r.dup ? `「${book.name}」里已经有这一条了` : `已记到「${book.name}」`);
    } catch (e) { toast(e.message); }
    tools.hidden = true;
    window.getSelection().removeAllRanges();
  }
  loadBooks();
  // 在笔记本页新建了本子再切回来，工具条也要跟着更新
  const onFocus = () => loadBooks();
  window.addEventListener("focus", onFocus);
  cleanups.push(() => window.removeEventListener("focus", onFocus));
  tools.querySelector('[data-act="ai"]').onclick = () => {
    if (!sel) return;
    aiSel = { text: sel.text, seq: sel.seq };
    tools.hidden = true;
    openPanel("ai");
  };

  // 点击已有的高亮：改颜色、写笔记、问 AI、取消高亮
  doc.addEventListener("click", (e) => {
    const mk = e.target.closest("mark.hl");
    if (!mk || !window.getSelection().isCollapsed) return;
    const m = marks.find((x) => String(x.id) === mk.dataset.mid);
    if (!m) return;
    const r = mk.getBoundingClientRect();
    pop.hidden = false;
    pop.innerHTML = `<div class="row" style="gap:6px">${COLORS.map(([c, n]) => `<button class="dot hl-${c}${m.color === c ? " on" : ""}" data-c="${c}" title="${n}"></button>`).join("")}
      <span class="spacer"></span><button class="btn sm ghost" data-a="ai">问 AI</button><button class="btn sm ghost danger" data-a="del">取消高亮</button></div>
      <textarea rows="2" placeholder="写一句笔记（可选）">${esc(m.note || "")}</textarea>
      <div class="row"><span class="spacer"></span><button class="btn sm" data-a="save">保存笔记</button></div>`;
    pop.style.top = Math.min(window.innerHeight - 170, r.bottom + 6) + "px";
    pop.style.left = Math.max(8, Math.min(window.innerWidth - 330, r.left)) + "px";
    const save = async (patch) => {
      Object.assign(m, patch);
      await apiPost("/api/docmarks", { id: m.id, color: m.color, note: m.note });
      unwrapMark(m.id);
      applyMark(m);
      if (panel === "marks") drawPanel();
    };
    pop.querySelectorAll("[data-c]").forEach((b) => (b.onclick = () => { save({ color: b.dataset.c }); pop.hidden = true; }));
    pop.querySelector('[data-a="save"]').onclick = () => { save({ note: pop.querySelector("textarea").value.trim() }); pop.hidden = true; toast("笔记已保存"); };
    pop.querySelector('[data-a="del"]').onclick = async () => {
      await apiPost("/api/docmarks/delete", { id: m.id });
      unwrapMark(m.id);
      marks = marks.filter((x) => x.id !== m.id);
      el.querySelector("#mcount").textContent = marks.length;
      pop.hidden = true;
      if (panel === "marks") drawPanel();
    };
    pop.querySelector('[data-a="ai"]').onclick = () => { aiSel = { text: m.text, seq: m.seq }; pop.hidden = true; openPanel("ai"); };
  });

  // ---------------------------------------------------------------- 例题作答
  const HOW = { "资料给出": "答案来自资料", "题库": "答案和解析来自题库", "其他资料": "答案和解析来自另一份资料", "补充解答": "资料没给答案，这是补充的解答",
    "软件计算": "资料没给答案，由软件按算式计算" };
  const qOf = (qe) => bySeq.get(+qe.dataset.q)?.[5];

  function expHTML(q) {
    const src = (q.how === "题库" || q.how === "其他资料") && q.bank?.src ? `（${esc(q.bank.src)}）` : "";
    const body = (q.exp || []).filter((e) => e.src || e.rows || !/^\s*[A-H]\s*[。．.]?\s*$/.test(e.t || "")).map((e) => e.src ? figHTML(e, "q-fig")
      : e.rows ? `<div class="table-wrap"><table class="rd-tbl">${e.rows.map((r) => `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`).join("")}</table></div>`
      : `<p>${rich(e.t || "")}</p>`).join("");
    return `${q.ans ? `<div class="q-ans">正确答案 <b>${esc(q.ans)}</b> <span class="small muted">${HOW[q.how] || ""}${src}</span></div>` : ""}
      ${body || (q.ans ? `<p class="small muted">资料里没有这道题的解析，可以点“问 AI”让它讲解解题过程。</p>` : "")}`;
  }

  function showResult(qe, choice, reveal) {
    const q = qOf(qe);
    if (!q) return;
    qe.classList.add("answered");
    const picked = (o) => !!choice && choice.includes(o);
    qe.querySelectorAll(".q-opt").forEach((b) => {
      b.disabled = true;
      b.classList.toggle("ok", !!q.ans && q.ans.includes(b.dataset.o));
      b.classList.toggle("bad", picked(b.dataset.o) && !!q.ans && !q.ans.includes(b.dataset.o));
      b.classList.toggle("picked", picked(b.dataset.o));
    });
    qe.querySelector('[data-qa="submit"]').hidden = true;
    qe.querySelectorAll(".q-stem input.blank").forEach((x) => checkBlank(x, true));
    const res = qe.querySelector(".q-res");
    if (choice && q.ans) {
      const ok = isCorrect(q, choice);
      res.innerHTML = ok ? `<span class="good">✓ 回答正确</span>` : `<span class="bad">✗ 选了 ${esc(choice)}，正确答案是 ${esc(q.ans)}</span>`;
    } else if (choice) {
      res.innerHTML = `<span class="muted">你选了 ${esc(choice)}；资料里没有给出这道题的答案，可以点“问 AI”</span>`;
    } else {
      res.innerHTML = q.ans ? `<span class="muted">正确答案是 ${esc(q.ans)}</span>` : `<span class="muted">资料里没有给出这道题的答案，可以点“问 AI”</span>`;
    }
    res.innerHTML += ` <span class="q-keys">· <kbd>Enter</kbd> 下一题</span>`;
    const exp = qe.querySelector(".q-exp");
    if (q.ans || reveal) {
      exp.innerHTML = expHTML(q);
      exp.hidden = !exp.innerHTML.trim();
    }
    qe.querySelector('[data-qa="show"]').hidden = true;
    qe.querySelector('[data-qa="redo"]').hidden = false;
  }

  const sortL = (x) => [...(x || "")].sort().join("");
  const isCorrect = (q, choice) => (isMulti(q) ? sortL(choice) === sortL(q.ans) : !!q.ans && q.ans.includes(choice));

  function resetQ(qe) {
    qe.classList.remove("answered");
    qe.querySelectorAll(".q-opt").forEach((b) => { b.disabled = false; b.classList.remove("ok", "bad", "picked", "sel"); });
    qe.querySelector(".q-res").innerHTML = KEYS_TIP(isMulti(qOf(qe)));
    qe.querySelector('[data-qa="submit"]').hidden = false;
    qe.querySelectorAll("input.blank").forEach((inp) => { inp.value = ""; inp.classList.remove("ok", "bad"); inp.title = ""; });
    qe.querySelectorAll(".blank-tip").forEach((x) => x.remove());
    const exp = qe.querySelector(".q-exp");
    exp.hidden = true;
    exp.innerHTML = "";
    qe.querySelector('[data-qa="show"]').hidden = false;
    qe.querySelector('[data-qa="redo"]').hidden = true;
  }

  const qShown = new Map(); // 点“重做”的时间，用来记作答用时
  let lastQAt = Date.now(); // 没点重做时按上一题作答（或打开资料）起算
  doc.querySelectorAll(".rd-q").forEach((qe) => {
    const q = qOf(qe);
    const prev = q && quiz[qkeyOf(q)];
    if (prev) showResult(qe, prev.choice, true);
  });

  // 当前在做的题：点过的那道；没点过就取屏幕里第一道。键盘 A–D 选择、Enter 确认看答案
  let activeQ = null;
  function setActive(qe) {
    if (activeQ === qe) return;
    activeQ?.classList.remove("active");
    activeQ = qe;
    qe?.classList.add("active");
  }
  function visibleQ() {
    const r = doc.getBoundingClientRect();
    return [...doc.querySelectorAll(".rd-q")].find((x) => {
      const b = x.getBoundingClientRect();
      return b.bottom > r.top + 30 && b.top < r.bottom - 30;
    }) || null;
  }

  function pick(qe, letter) {
    const b = qe.querySelector(`.q-opt[data-o="${letter}"]`);
    if (!b || b.disabled) return false;
    if (isMulti(qOf(qe))) b.classList.toggle("sel");
    else {
      qe.querySelectorAll(".q-opt.sel").forEach((x) => x !== b && x.classList.remove("sel"));
      b.classList.add("sel");
    }
    return true;
  }

  // 确认作答：有选中的选项就判对错；什么都没选就直接显示答案
  function submitQ(qe) {
    if (qe.classList.contains("answered")) return;
    const q = qOf(qe);
    if (!q) return;
    checkStemBlanks(qe);
    const choice = sortL([...qe.querySelectorAll(".q-opt.sel")].map((b) => b.dataset.o).join(""));
    if (!choice) { showResult(qe, null, true); return; }
    const correct = isCorrect(q, choice);
    showResult(qe, choice);
    quiz[qkeyOf(q)] = { choice, correct: correct ? 1 : 0 };
    const started = qShown.get(qe) || lastQAt;
    lastQAt = Date.now();
    apiPost("/api/docquiz", {
      doc: d.id, qkey: qkeyOf(q), choice, correct, title: d.title,
      ...(q.bank?.id && q.ans && choice.length === 1 ? { qid: q.bank.id, module: q.bank.module, chosen: "ABCDEFGH".indexOf(choice), seconds: Math.min(600, Math.round((Date.now() - started) / 1000)) } : {}),
    }).catch(() => {});
  }

  function nextQ(qe) {
    const all = [...doc.querySelectorAll(".rd-q")];
    const nx = all[all.indexOf(qe) + 1];
    if (!nx) { toast("这份资料的例题做完了"); return; }
    setActive(nx);
    nx.scrollIntoView({ block: "center", behavior: "smooth" });
  }

  doc.addEventListener("click", async (e) => {
    const qe = e.target.closest(".rd-q");
    if (!qe) return;
    const q = qOf(qe);
    if (!q) return;
    setActive(qe);
    const opt = e.target.closest(".q-opt");
    if (opt) {
      if (opt.disabled) return;
      // 单选题再点一次已选中的选项 = 确认
      if (!isMulti(q) && opt.classList.contains("sel")) submitQ(qe);
      else pick(qe, opt.dataset.o);
      return;
    }
    const act = e.target.closest("[data-qa]")?.dataset.qa;
    if (act === "submit") {
      if (!qe.querySelector(".q-opt.sel") && ![...qe.querySelectorAll("input.blank")].some((x) => x.value.trim())) { toast("先选择选项（或按 Enter 直接看答案）"); return; }
      submitQ(qe);
    } else if (act === "show") showResult(qe, null, true);
    else if (act === "redo") { resetQ(qe); qShown.set(qe, Date.now()); }
    else if (act === "ai") {
      const exp = qe.querySelector(".q-exp");
      exp.hidden = false;
      const box = document.createElement("div");
      box.className = "ai-out q-ai";
      box.textContent = "AI 正在解题…";
      exp.appendChild(box);
      const st = await getAIStatus();
      if (!st.installed || !st.configured) { box.innerHTML = `AI 助教还没启用，<a href="#/settings">去设置里填写 API Key</a>。`; return; }
      const text = plain(q.stem) + "\n" + q.opts.map(([a, o]) => `${a}. ${plain(o)}`).join("\n") + (q.ans ? `\n（资料给出的答案：${q.ans}）` : "");
      try {
        await streamAI("reader", {
          title: d.title, section: sectionOf(+qe.dataset.q), text, context: contextOf(+qe.dataset.q),
          question: q.ans ? "请讲解这道题：为什么选这个答案，其他选项错在哪里；计算题写出快速算法和估算步骤。" : "请解答这道题：给出答案，并写出详细的解题思路；计算题写出快速算法和估算步骤。",
        }, (t) => (box.textContent = t));
      } catch (err) { box.textContent = "出错了：" + err.message; }
    }
  });

  // ---------------------------------------------------------------- 填空
  // 回车对答案：有参考答案的判对错并给出答案；资料没给答案的空也提示一声
  const toNum = (v) => {
    const t = String(v).trim().replace(/[，,\s]/g, "");
    let m = t.match(/^(-?\d+(?:\.\d+)?)\/(\d+(?:\.\d+)?)$/);
    if (m) return +m[1] / +m[2];
    m = t.match(/^(-?\d+(?:\.\d+)?)%$/);
    if (m) return +m[1] / 100;
    return /^-?\d+(?:\.\d+)?$/.test(t) ? +t : NaN;
  };
  const squashT = (t) => String(t || "").replace(/[\s，,。.、“”"'‘’]/g, "");
  function blankTip(inp, text, cls) {
    let tip = inp.nextElementSibling;
    if (!tip?.classList.contains("blank-tip")) {
      tip = document.createElement("span");
      tip.className = "blank-tip";
      inp.after(tip);
    }
    tip.textContent = text;
    tip.classList.toggle("muted", cls === "muted");
  }
  function checkBlank(inp, force) {
    const a = inp.dataset.a;
    const v = inp.value.trim();
    inp.classList.remove("ok", "bad");
    if (!a) {
      if (force) blankTip(inp, v ? "资料没给这一空的答案" : "资料没给这一空的答案，可以问 AI", "muted");
      return null;
    }
    if (!v) {
      if (force) blankTip(inp, a);
      return null;
    }
    const x = toNum(v), y = toNum(a);
    const ok = squashT(v) === squashT(a) || (!isNaN(x) && !isNaN(y) && Math.abs(x - y) <= Math.abs(y) * 0.01 + 1e-9);
    inp.classList.add(ok ? "ok" : "bad");
    inp.title = ok ? "正确" : `参考答案：${a}`;
    if (!ok) blankTip(inp, a);
    else if (inp.nextElementSibling?.classList.contains("blank-tip")) inp.nextElementSibling.remove();
    return ok;
  }
  // 选择题题干里的空：填的内容正好是某个选项，就当选了那个选项
  function checkStemBlanks(qe) {
    const q = qOf(qe);
    const ins = [...qe.querySelectorAll(".q-stem input.blank")];
    const vals = ins.map((x) => squashT(x.value));
    if (!ins.length || !vals.some(Boolean)) return;
    ins.forEach((x) => checkBlank(x, true));
    if (qe.querySelector(".q-opt.sel")) return;
    const hit = q.opts.find(([, o]) => {
      const parts = plain(o).split(/[，,、；;\s]+/).filter(Boolean).map(squashT);
      return vals.length === 1 ? squashT(plain(o)) === vals[0] || parts[0] === vals[0] : parts.join("|") === vals.join("|");
    });
    if (hit) pick(qe, hit[0]);
  }

  doc.addEventListener("keydown", (e) => {
    if (!e.target.matches?.("input.blank") || e.key !== "Enter") return;
    e.preventDefault();
    e.stopPropagation();
    const qe = e.target.closest(".rd-q");
    if (qe) {
      setActive(qe);
      const ins = [...qe.querySelectorAll(".q-stem input.blank")];
      const nx = ins[ins.indexOf(e.target) + 1];
      if (nx && !nx.value.trim()) { nx.focus(); return; }
      submitQ(qe);
      return;
    }
    checkBlank(e.target, true);
    const all = [...doc.querySelectorAll("input.blank")].filter((x) => !x.closest(".rd-q"));
    all[all.indexOf(e.target) + 1]?.focus();
  });
  doc.addEventListener("focusout", (e) => {
    if (e.target.matches?.("input.blank") && !e.target.closest(".rd-q") && e.target.value.trim()) checkBlank(e.target);
  });

  // 键盘做题：A–H 选择（多选题再按一次取消），Enter 确认并看答案；看过答案后 Enter 跳到下一题
  const onQuizKey = (e) => {
    if (!el.isConnected || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.target.closest?.("input, textarea, select, [contenteditable]")) return;
    const k = e.key.length === 1 ? e.key.toUpperCase() : e.key;
    if (k !== "Enter" && !/^[A-H]$/.test(k)) return;
    let qe = activeQ && activeQ.isConnected ? activeQ : null;
    if (qe) {
      const r = qe.getBoundingClientRect(), dr = doc.getBoundingClientRect();
      if (r.bottom < dr.top || r.top > dr.bottom) qe = null; // 已经滚走了
    }
    qe = qe || visibleQ();
    if (!qe) return;
    setActive(qe);
    if (k === "Enter") {
      e.preventDefault();
      if (qe.classList.contains("answered")) nextQ(qe);
      else submitQ(qe);
    } else if (!qe.classList.contains("answered") && pick(qe, k)) e.preventDefault();
  };
  document.addEventListener("keydown", onQuizKey);
  cleanups.push(() => document.removeEventListener("keydown", onQuizKey));

  // ---------------------------------------------------------------- 侧栏：标注 / 查找 / AI
  function openPanel(kind) {
    panel = panel === kind && kind !== "ai" ? null : kind;
    drawPanel();
  }

  async function drawPanel(arg) {
    panelEl.hidden = !panel;
    if (!panel) return;
    if (panel === "marks") {
      const list = marks.slice().sort((a, b) => a.seq - b.seq || a.start - b.start);
      panelEl.innerHTML = `<div class="row"><b>我的标注</b><span class="small muted">${list.length} 处</span><span class="spacer"></span><button class="btn sm ghost" data-close>关闭</button></div>
        ${list.length ? list.map((m) => `<div class="pm" data-go="${m.seq}"><span class="dot hl-${m.color}"></span><div><div class="pm-t">${esc(m.text.slice(0, 120))}</div>
          ${m.note ? `<div class="small ink2">✎ ${esc(m.note)}</div>` : ""}<div class="small muted">${m.lost ? "资料重新整理过，正文里找不到这段了" : esc(sectionOf(m.seq))}</div></div></div>`).join("")
          : `<p class="small muted">选中正文里的文字，点颜色就能高亮；高亮可以写笔记。</p>`}`;
    } else if (panel === "find") {
      const q = arg ?? el.querySelector("#findq").value.trim();
      panelEl.innerHTML = `<div class="row"><b>查找“${esc(q)}”</b><span class="spacer"></span><button class="btn sm ghost" data-close>关闭</button></div><div class="small muted">搜索中…</div>`;
      const r = await apiGet(`/api/docs/search?q=${encodeURIComponent(q)}&doc=${encodeURIComponent(d.id)}`);
      const re = new RegExp(q.split(/\s+/).filter(Boolean).map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|"), "g");
      panelEl.innerHTML = `<div class="row"><b>查找“${esc(q)}”</b><span class="small muted">${r.hits.length} 处</span><span class="spacer"></span><button class="btn sm ghost" data-close>关闭</button></div>
        ${r.hits.length ? r.hits.sort((a, b) => a.seq - b.seq).map((h) => `<div class="pm" data-go="${h.seq}" data-flash="${esc(q)}"><div><div class="pm-t">${esc(h.snippet).replace(re, (x) => `<mark>${x}</mark>`)}</div>
          <div class="small muted">${esc(sectionOf(h.seq))}</div></div></div>`).join("") : `<p class="small muted">没有找到</p>`}`;
    } else if (panel === "ai") {
      const st = await getAIStatus();
      const ready = st.installed && st.configured;
      panelEl.innerHTML = `<div class="row"><b>问 AI</b><span class="spacer"></span><button class="btn sm ghost" data-close>关闭</button></div>
        ${aiSel ? `<blockquote class="ai-quote">${esc(aiSel.text.slice(0, 400))}${aiSel.text.length > 400 ? "…" : ""}</blockquote>`
          : `<p class="small muted">先在正文里选中一段文字，再点工具条上的“问 AI”。也可以直接提问这份资料相关的问题。</p>`}
        ${ready ? "" : `<p class="small" style="color:var(--bad)">AI 助教还没启用，<a href="#/settings">去设置里填写 API Key</a>。</p>`}
        <div class="ai-chips">${AI_PRESETS.map((p) => `<button class="btn sm" data-ask="${esc(p)}">${esc(p)}</button>`).join("")}</div>
        <textarea id="aiq" rows="2" placeholder="或者自己写问题"></textarea>
        <div class="row"><span class="spacer"></span><button class="btn sm primary" id="aigo" ${ready ? "" : "disabled"}>提问</button></div>
        <div id="aiout"></div>`;
      const ask = async (question) => {
        const out = el.querySelector("#aiout");
        const item = document.createElement("div");
        item.className = "ai-item";
        item.innerHTML = `<div class="small ink2">问：${esc(question)}</div><div class="ai-out">AI 正在思考…</div>`;
        out.prepend(item);
        const box = item.querySelector(".ai-out");
        const seq = aiSel ? aiSel.seq : curSeq;
        try {
          await streamAI("reader", {
            title: d.title, section: sectionOf(seq), text: aiSel ? aiSel.text : contextOf(seq),
            context: contextOf(seq), question,
          }, (t) => (box.textContent = t));
        } catch (e) { box.textContent = "出错了：" + e.message; }
      };
      panelEl.querySelectorAll("[data-ask]").forEach((b) => (b.onclick = () => ready && ask(b.dataset.ask)));
      const go = panelEl.querySelector("#aigo");
      go.onclick = () => {
        const q = panelEl.querySelector("#aiq").value.trim();
        if (!q) { toast("先写下问题"); return; }
        ask(q);
      };
    }
    panelEl.querySelector("[data-close]").onclick = () => { panel = null; drawPanel(); };
    panelEl.querySelectorAll("[data-go]").forEach((x) => (x.onclick = () => goTo(+x.dataset.go, x.dataset.flash)));
  }

  // ---------------------------------------------------------------- 跳转、目录、进度
  function goTo(seq, flash) {
    const be = doc.querySelector(`[data-seq="${seq}"]`) || [...doc.querySelectorAll("[data-seq]")].find((x) => +x.dataset.seq >= seq);
    if (!be) return;
    be.scrollIntoView({ block: "start" });
    doc.scrollTop -= 12;
    be.classList.remove("rd-flash");
    void be.offsetWidth;
    be.classList.add("rd-flash");
    if (flash) {
      if (be.matches(".rd-tree")) showTreeView(be, "outline");
      be.querySelectorAll("details").forEach((x) => (x.open = true)); // 命中在插图的识别文字里
      const terms = flash.split(/\s+/).filter(Boolean);
      textNodes(be).forEach((tn) => {
        const t = terms.find((x) => tn.data.includes(x));
        if (!t) return;
        const i = tn.data.indexOf(t);
        const r = document.createRange();
        r.setStart(tn, i);
        r.setEnd(tn, i + t.length);
        const mk = document.createElement("mark");
        mk.className = "find-hit";
        r.surroundContents(mk);
        setTimeout(() => { if (mk.isConnected) { mk.replaceWith(...mk.childNodes); be.normalize(); } }, 2500);
      });
    }
  }

  function revealToc(i) {
    // 展开当前条目的所有上级
    const items = [...tocEl.querySelectorAll(".toc-i[data-i]")];
    if (!items.length) return;
    let depth = +items[i].dataset.depth;
    items[i].hidden = false;
    for (let k = i - 1; k >= 0 && depth > 0; k--) {
      const dk = +items[k].dataset.depth;
      if (dk < depth) {
        depth = dk;
        items[k].hidden = false;
        const c = items[k].querySelector(".caret[data-fold]");
        if (c && c.textContent === "▸") toggleFold(k, true);
      }
    }
  }

  function toggleFold(i, open) {
    const items = [...tocEl.querySelectorAll(".toc-i[data-i]")];
    const base = +items[i].dataset.depth;
    const caret = items[i].querySelector(".caret");
    const willOpen = open ?? caret.textContent === "▸";
    caret.textContent = willOpen ? "▾" : "▸";
    for (let k = i + 1; k < items.length && +items[k].dataset.depth > base; k++) {
      const dk = +items[k].dataset.depth;
      if (!willOpen) items[k].hidden = true;
      else if (dk === base + 1) items[k].hidden = false;
    }
  }

  tocEl.addEventListener("click", (e) => {
    const f = e.target.closest("[data-fold]");
    if (f) { e.stopPropagation(); toggleFold(+f.dataset.fold); return; }
    const b = e.target.closest("[data-go]");
    if (b) goTo(+b.dataset.go);
  });
  // 普通资料展开一级目录；长词条目录保留分组折叠。
  tocEl.querySelectorAll(".toc-i[data-i]").forEach((x) => {
    if (!denseToc && +x.dataset.depth === 0 && x.querySelector(".caret[data-fold]")) toggleFold(+x.dataset.i, true);
  });

  let activeToc = -1;
  function spy() {
    const r = doc.getBoundingClientRect();
    let target = document.elementFromPoint(r.left + r.width / 2, r.top + 24);
    let be = target?.closest?.("[data-seq]");
    if (!be) {
      const all = doc.querySelectorAll("[data-seq]");
      be = [...all].find((x) => x.getBoundingClientRect().bottom > r.top + 10);
    }
    if (!be) return;
    curSeq = +be.dataset.seq;
    el.querySelector("#pct").textContent = `已读 ${pct()}%`;
    let idx = -1;
    d.toc.forEach(([, , s], i) => { if (s <= curSeq) idx = i; });
    if (idx !== activeToc) {
      tocEl.querySelectorAll(".toc-i.on").forEach((x) => x.classList.remove("on"));
      const it = tocEl.querySelector(`.toc-i[data-i="${idx}"]`);
      if (it) {
        revealToc(idx);
        it.classList.add("on");
        const tr = tocEl.getBoundingClientRect(), ir = it.getBoundingClientRect();
        if (ir.top < tr.top || ir.bottom > tr.bottom) tocEl.scrollTop += ir.top - tr.top - tr.height / 3;
      }
      activeToc = idx;
    }
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      const p = Math.max(prog.pct || 0, pct());
      apiPost("/api/docs/progress", { doc: d.id, seq: curSeq, pct: p }).catch(() => {});
    }, 1500);
  }
  let spyRaf = 0;
  doc.addEventListener("scroll", () => {
    tools.hidden = true;
    pop.hidden = true;
    cancelAnimationFrame(spyRaf);
    spyRaf = requestAnimationFrame(spy);
  });

  // ---------------------------------------------------------------- 顶栏
  const setFont = (n) => {
    fontSize = Math.max(14, Math.min(24, n));
    doc.style.fontSize = fontSize + "px";
    store.set("reader-font", fontSize);
  };
  el.querySelector("#fminus").onclick = () => setFont(fontSize - 1);
  el.querySelector("#fplus").onclick = () => setFont(fontSize + 1);
  el.querySelector("#tocbtn").onclick = () => {
    const body = el.querySelector(".rd-body");
    body.classList.toggle("no-toc");
    store.set("reader-toc", !body.classList.contains("no-toc"));
  };
  el.querySelector("#marksbtn").onclick = () => openPanel("marks");
  el.querySelector("#aibtn").onclick = () => { aiSel = currentSelection() ? { text: currentSelection().text, seq: currentSelection().seq } : aiSel; panel = "ai"; drawPanel(); };
  el.querySelector("#findf").onsubmit = (e) => {
    e.preventDefault();
    const q = el.querySelector("#findq").value.trim();
    if (q) { panel = "find"; drawPanel(q); }
  };
  el.querySelector("#fav").onclick = async (e) => {
    prog.fav = !prog.fav;
    await apiPost("/api/docs/progress", { doc: d.id, fav: prog.fav });
    e.target.textContent = prog.fav ? "★ 已收藏" : "☆ 收藏";
  };
  el.querySelector("#done").onclick = async (e) => {
    prog.done = !prog.done;
    await apiPost("/api/docs/progress", { doc: d.id, done: prog.done, pct: prog.done ? 100 : pct() });
    e.target.textContent = prog.done ? "✓ 已读完" : "标记读完";
  };
  const onKey = (e) => {
    if (!el.isConnected) return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f") {
      e.preventDefault();
      el.querySelector("#findq").focus();
    } else if (e.key === "Escape") {
      tools.hidden = true;
      pop.hidden = true;
      if (panel) { panel = null; drawPanel(); }
    }
  };
  document.addEventListener("keydown", onKey);
  cleanups.push(() => document.removeEventListener("keydown", onKey));

  // 打开时回到上次读到的位置
  requestAnimationFrame(() => {
    if (curSeq > 0 || startFlash) goTo(curSeq, startFlash);
    if (startFlash) el.querySelector("#findq").value = startFlash;
    spy();
  });

  return () => {
    cleanups.forEach((f) => f());
    clearTimeout(saveTimer);
    const minutes = Math.round((Date.now() - opened) / 60000);
    const subj = (d.subj || []).find((s) => SUBJ_MODULE[s]);
    apiPost("/api/docs/progress", {
      doc: d.id, seq: curSeq, pct: Math.max(prog.pct || 0, pct()),
      minutes: minutes >= 1 ? Math.min(minutes, 180) : 0, module: subj ? SUBJ_MODULE[subj] : "综合",
    }).catch(() => {});
  };
}
