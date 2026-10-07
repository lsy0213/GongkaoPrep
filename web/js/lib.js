// 公共工具：接口请求、内容缓存、HTML 转义、Markdown、提示、图表、AI 流式输出

export const MODULES = ["政治理论", "常识判断", "言语理解与表达", "数量关系", "判断推理", "资料分析"];
export const MODULE_SHORT = {
  "政治理论": "政治", "常识判断": "常识", "言语理解与表达": "言语", "数量关系": "数量", "判断推理": "判断", "资料分析": "资料",
};
export const LETTERS = "ABCD";

export async function apiGet(path) {
  const r = await fetch(path, { cache: "no-store" });
  const data = await r.json().catch(() => ({ error: "服务器没有返回有效数据" }));
  if (!r.ok || data.error) throw new Error(data.error || `请求失败（${r.status}）`);
  return data;
}

export async function apiPost(path, body = {}) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({ error: "服务器没有返回有效数据" }));
  if (!r.ok || data.error) throw new Error(data.error || `请求失败（${r.status}）`);
  return data;
}

const cache = new Map();
export function content(name) {
  if (!cache.has(name)) {
    const url = "/content/" + name;
    const p = fetch(url).then((r) => {
      if (!r.ok) throw new Error("读取内容失败：" + name);
      return name.endsWith(".json") ? r.json() : r.text();
    });
    p.catch(() => cache.delete(name));
    cache.set(name, p);
  }
  return cache.get(name);
}

// ---------------------------------------------------------------- 题库（服务器端数据库，按需取题）

let metaPromise = null;
const qCache = new Map(), mCache = new Map(), sCache = new Map();

// 题库概况：各来源题量、题源列表（真题卷、千题册）
export function bankMeta(refresh = false) {
  if (refresh || !metaPromise) {
    metaPromise = apiGet("/api/bank/meta").then((m) => {
      m.sourceById = Object.fromEntries(m.sources.map((x) => [x.id, x]));
      m.papers = m.sources.filter((x) => x.kind === "paper");
      m.books = m.sources.filter((x) => x.kind === "book");
      return m;
    });
    metaPromise.catch(() => (metaPromise = null));
  }
  return metaPromise;
}

// 题库有变化（整理完资料、导入题目）后清掉缓存
export function clearBankCache() {
  metaPromise = null;
  qCache.clear(); mCache.clear(); sCache.clear();
}

// 按条件让服务器选题，返回题目 id（资料分析等同一材料的题保持成组）
export async function pickQuestions(params) {
  return (await apiPost("/api/bank/pick", params)).ids;
}

// 按 id 取题目详情；返回 { questions, mat(id), source(id) }
export async function getQuestions(ids) {
  const miss = ids.filter((id) => !qCache.has(id));
  for (let i = 0; i < miss.length; i += 800) {
    const r = await apiPost("/api/bank/get", { ids: miss.slice(i, i + 800) });
    r.questions.forEach((q) => qCache.set(q.id, q));
    r.materials.forEach((m) => mCache.set(m.id, m));
    Object.values(r.sources).forEach((x) => sCache.set(x.id, x));
  }
  return {
    questions: ids.map((id) => qCache.get(id)).filter(Boolean),
    mat: (id) => mCache.get(id),
    source: (id) => sCache.get(id),
  };
}

// 原卷截图：segs = [[页, x0, y0, x1, y1], …]（题目可能跨页），fid 是资料文件 id
export function cropHTML(segs, fid) {
  if (!segs || !segs.length || !fid) return "";
  return `<div class="crop">${segs.map((s) => `<img loading="lazy" alt="原卷截图"
    src="/api/crop/${encodeURIComponent(fid)}/${s[0]}/${s.slice(1).map((v) => (+v).toFixed(1)).join(",")}.png">`).join("")}</div>`;
}

// 题目来源的短标签：内置题为空，真题如“2024 国考”，千题册如“2026年广东省”
export function srcLabel(q) {
  if (!q || !q.real) return "";
  if (q.src === "千题册") return q.origin || "千题册";
  return `${q.year} ${q.src}`;
}

// 题目是否需要看原卷才能做（图形推理、图表题、扫描版填空、没能拆出选项文字的题）
export function needsCrop(q) {
  return !!(q.real && q.crop && q.crop.length && (q.fig || !q.options || q.sub === "图形推理"));
}

export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// 带公式的文字：\( \)、\[ \]（资料里摘来的）和 $ $、$$ $$（自己手写的）用 KaTeX 排版，⦅分子⁄分母⦆ 显示成竖排分数
const MATH_PARTS = /(\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|\$\$[\s\S]+?\$\$|\$[^$\n]+?\$)/g;
export function mathText(text) {
  return String(text ?? "").split(MATH_PARTS).map((part, i) => {
    if (i % 2) {
      const displayMode = part.startsWith("\\[") || part.startsWith("$$");
      const tex = part.startsWith("$$") ? part.slice(2, -2) : part.startsWith("$") ? part.slice(1, -1) : part.slice(2, -2);
      try {
        if (window.katex) return window.katex.renderToString(tex, { displayMode, throwOnError: true, trust: false, maxExpand: 1000 });
      } catch { /* 公式写错时显示原文 */ }
      return esc(part);
    }
    return esc(part)
      .replace(/⦅([^⁄⦆]*)⁄([^⦆]*)⦆/g, (_m, a, b) => `<span class="frac"><span>${a}</span><span>${b}</span></span>`)
      .replace(/\n/g, "<br>");
  }).join("");
}

export function toast(msg, ms = 2200) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove("show"), ms);
}

// 界面偏好（主题、草稿、已学章节……）保存在本机数据库里；启动时整体读入内存，写入时合并后批量提交
const prefs = {};
const pending = {};
let flushTimer = null;
export async function initStore() {
  try { Object.assign(prefs, await apiGet("/api/prefs")); } catch { /* 读不到就用默认值 */ }
}
function flush() {
  const body = { ...pending };
  for (const k of Object.keys(pending)) delete pending[k];
  apiPost("/api/prefs", body).catch(() => {});
}
export const store = {
  get(key, fallback = null) {
    return key in prefs ? prefs[key] : fallback;
  },
  set(key, value) {
    prefs[key] = value;
    pending[key] = value;
    clearTimeout(flushTimer);
    flushTimer = setTimeout(flush, 400);
  },
};
window.addEventListener("beforeunload", () => { if (Object.keys(pending).length) flush(); });

// 导出文件：桌面窗口里弹“另存为”，浏览器里走下载
export async function saveFile(filename, text) {
  if (window.pywebview?.api?.save_text) {
    const path = await window.pywebview.api.save_text(filename, text);
    return path || "";
  }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  return filename;
}

export function todayISO(d = new Date()) {
  const z = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`;
}

export function daysBetween(a, b) {
  const da = new Date(a + "T00:00:00"), db = new Date(b + "T00:00:00");
  return Math.round((db - da) / 86400000);
}

export function fmtClock(sec) {
  sec = Math.max(0, Math.round(sec));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  const z = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${z(m)}:${z(s)}` : `${z(m)}:${z(s)}`;
}

export function fmtMinutes(min) {
  min = Math.round(min || 0);
  if (min < 60) return `${min} 分钟`;
  return `${Math.floor(min / 60)} 小时 ${min % 60 ? (min % 60) + " 分" : ""}`.trim();
}

// 后台整理任务的进度框（资料库、时政晨读页共用）：进度条、当前文件、排队的任务、取消按钮
export function jobProgressHTML(job, hint = "可以先去别的页面，整理在后台进行") {
  const pct = job.total ? Math.round((job.done / job.total) * 100) : 0;
  const queue = job.queue?.length ? `<div class="small muted mt">排队中：${job.queue.map(esc).join("、")}</div>` : "";
  return `<div class="job-box" id="job"><div class="row"><b>${esc(job.name)}</b><span class="small muted">${esc(job.step)}</span><span class="spacer"></span>
    <span class="small muted">${job.cancelling ? "正在停止，处理完当前文件就停…" : esc(hint)}</span>
    ${job.cancelling ? "" : `<button class="btn sm ghost" data-job-cancel title="已经整理好的部分会保留，下次接着整理">停止</button>`}</div>
    <div class="progress mt"><i style="width:${pct}%"></i></div>
    <div class="small muted mt" style="overflow:hidden;white-space:nowrap;text-overflow:ellipsis">${esc(job.msg)}</div>${queue}</div>`;
}

document.addEventListener("click", async (e) => {
  const b = e.target.closest?.("[data-job-cancel]");
  if (!b) return;
  if (!b.dataset.armed) { b.dataset.armed = "1"; b.textContent = "确认停止"; return; }
  b.disabled = true;
  try { await apiPost("/api/jobs/cancel"); toast("正在停止，已经整理好的部分会保留"); } catch (err) { toast(err.message, 4000); }
});

export function jobDoneText(job, okText) {
  if (job.cancelled) return "已停止整理；已经整理好的部分保留了，下次接着整理";
  return job.error ? "整理出错：" + job.error : okText;
}

export function fmtBytes(n) {
  n = Number(n) || 0;
  if (n >= 2 ** 30) return (n / 2 ** 30).toFixed(n >= 10 * 2 ** 30 ? 0 : 1) + " GB";
  if (n >= 2 ** 20) return (n / 2 ** 20).toFixed(n >= 100 * 2 ** 20 ? 0 : 1) + " MB";
  if (n >= 1024) return Math.round(n / 1024) + " KB";
  return n + " B";
}

export function shuffle(arr) {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

export function countChars(s) {
  // 申论按字计数：去掉空白
  return (s || "").replace(/\s/g, "").length;
}

export function parseHash() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [path, qs] = raw.split("?");
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  const query = Object.fromEntries(new URLSearchParams(qs || ""));
  return { route: parts[0] || "", parts, query };
}

// ---------------------------------------------------------------- Markdown（教程用的子集）

function inline(s) {
  return esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/==([^=]+)==/g, "<mark>$1</mark>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/\[([^\]]+)\]\((#\/[^)\s]*)\)/g, '<a href="$2">$1</a>');
}

export function md(text) {
  const lines = text.replace(/\r/g, "").split("\n");
  const out = [];
  let i = 0;
  const isTableSep = (l) => /^\s*\|?\s*:?-{2,}/.test(l) && l.includes("-");
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    let m;
    if ((m = line.match(/^(#{1,4})\s+(.*)$/))) {
      const n = m[1].length;
      out.push(`<h${n}>${inline(m[2])}</h${n}>`);
      i++;
    } else if (/^---+\s*$/.test(line)) {
      out.push("<hr>");
      i++;
    } else if (line.startsWith(">")) {
      const buf = [];
      while (i < lines.length && lines[i].startsWith(">")) buf.push(lines[i++].replace(/^>\s?/, ""));
      out.push(`<blockquote>${md(buf.join("\n"))}</blockquote>`);
    } else if (line.includes("|") && i + 1 < lines.length && isTableSep(lines[i + 1])) {
      const cells = (l) => l.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
      const head = cells(line);
      i += 2;
      const body = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) body.push(cells(lines[i++]));
      out.push(
        `<div class="table-wrap"><table><thead><tr>${head.map((c) => `<th>${inline(c)}</th>`).join("")}</tr></thead><tbody>` +
        body.map((r) => `<tr>${r.map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`).join("") +
        "</tbody></table></div>"
      );
    } else if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\./.test(line);
      const items = [];
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) {
        let item = lines[i++].replace(/^\s*([-*]|\d+\.)\s+/, "");
        // 缩进的续行和子列表并入当前项
        while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !/^\s*([-*]|\d+\.)\s+/.test(lines[i])) {
          item += " " + lines[i++].trim();
        }
        const sub = [];
        while (i < lines.length && /^\s{2,}([-*]|\d+\.)\s+/.test(lines[i])) sub.push(lines[i++].trim());
        items.push(inline(item) + (sub.length ? md(sub.join("\n")) : ""));
      }
      const tag = ordered ? "ol" : "ul";
      out.push(`<${tag}>${items.map((x) => `<li>${x}</li>`).join("")}</${tag}>`);
    } else {
      const buf = [];
      while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|>|---+\s*$|\s*([-*]|\d+\.)\s+)/.test(lines[i]) &&
        !(lines[i].includes("|") && i + 1 < lines.length && isTableSep(lines[i + 1]))) {
        buf.push(lines[i++]);
      }
      out.push(`<p>${buf.map(inline).join("<br>")}</p>`);
    }
  }
  return out.join("\n");
}

// ---------------------------------------------------------------- 图表

export function barChart(items, { value = "v", label = "l", today = -1, unit = "" } = {}) {
  const max = Math.max(1, ...items.map((x) => x[value] || 0));
  return `<div class="bars">${items.map((x, i) => {
    const v = x[value] || 0;
    return `<div class="b${i === today ? " today" : ""}" title="${esc(x[label])}：${v}${unit}">
      <span class="bv">${v || ""}</span><i style="height:${(v / max) * 100}%"></i><span class="bl">${esc(x[label])}</span></div>`;
  }).join("")}</div>`;
}

export function accuracyBars(rows) {
  return rows.map((r) => {
    const cls = r.total === 0 ? "" : r.acc < 60 ? "low" : r.acc < 75 ? "mid" : "";
    return `<div class="hbar"><span>${esc(r.name)}</span>
      <span class="track"><i class="${cls}" style="width:${r.total ? r.acc : 0}%"></i></span>
      <span class="v">${r.total ? r.acc.toFixed(0) + "%" : "未练"}</span></div>`;
  }).join("");
}

export function lineChart(points, { w = 640, h = 180, key = "v", key2 = null, labelEvery = 5 } = {}) {
  const pad = { l: 34, r: 24, t: 12, b: 24 };
  const max = Math.max(1, ...points.map((p) => Math.max(p[key] || 0, key2 ? p[key2] || 0 : 0)));
  const nice = Math.ceil(max / 4) * 4 || 4;
  const iw = w - pad.l - pad.r, ih = h - pad.t - pad.b;
  const x = (i) => pad.l + (points.length === 1 ? iw / 2 : (i / (points.length - 1)) * iw);
  const y = (v) => pad.t + ih - (v / nice) * ih;
  const path = (k) => points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p[k] || 0).toFixed(1)}`).join("");
  const grid = [0, 1, 2, 3, 4].map((g) => {
    const v = (nice / 4) * g;
    return `<line class="grid-line" x1="${pad.l}" x2="${w - pad.r}" y1="${y(v)}" y2="${y(v)}"/><text x="${pad.l - 6}" y="${y(v) + 4}" text-anchor="end">${Math.round(v)}</text>`;
  }).join("");
  const labels = points.map((p, i) => (i % labelEvery === 0 || i === points.length - 1)
    ? `<text x="${x(i)}" y="${h - 6}" text-anchor="middle">${esc(p.l)}</text>` : "").join("");
  const area = `${path(key)}L${x(points.length - 1)},${y(0)}L${x(0)},${y(0)}Z`;
  const last = points.length - 1;
  return `<svg class="chart" viewBox="0 0 ${w} ${h}" width="100%" preserveAspectRatio="xMidYMid meet" role="img">
    ${grid}<path class="area" d="${area}"/><path class="line" d="${path(key)}"/>
    ${key2 ? `<path class="line2" d="${path(key2)}"/>` : ""}
    <circle class="dot" cx="${x(last)}" cy="${y(points[last][key] || 0)}" r="3.5"/>${labels}</svg>`;
}

// ---------------------------------------------------------------- AI

let aiStatus = null;
export async function getAIStatus(refresh = false) {
  if (refresh || !aiStatus) aiStatus = apiGet("/api/ai/status").catch(() => ({ installed: false, configured: false }));
  return aiStatus;
}

export async function streamAI(kind, body, onText, signal) {
  const r = await fetch("/api/ai/" + kind, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    throw new Error(data.error || "AI 请求失败");
  }
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let text = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    text += dec.decode(value, { stream: true });
    onText(text);
  }
  return text;
}

// 一个可复用的“问 AI”区块：按钮 + 输出区，未配置时给出指引
export function mountAIBox(container, { label, kind, getBody, onDone }) {
  container.innerHTML = `<div class="row"><button class="btn sm" data-ai-go>${esc(label)}</button>
    <span class="small muted" data-ai-hint></span></div><div class="ai-box" data-ai-wrap hidden><div class="ai-out" data-ai-out></div>
    <div class="row mt" data-ai-ctl hidden><button class="btn sm" data-ai-stop>停止</button></div></div>`;
  const go = container.querySelector("[data-ai-go]");
  const hint = container.querySelector("[data-ai-hint]");
  const wrap = container.querySelector("[data-ai-wrap]");
  const out = container.querySelector("[data-ai-out]");
  const ctl = container.querySelector("[data-ai-ctl]");
  let abort = null;
  getAIStatus().then((s) => {
    if (!s.installed || !s.configured) {
      hint.innerHTML = `AI 助教未启用，<a href="#/settings">去设置</a>`;
    }
  });
  container.querySelector("[data-ai-stop]").onclick = () => abort?.abort();
  go.onclick = async () => {
    let body;
    try { body = getBody(); } catch (e) { toast(e.message); return; }
    wrap.hidden = false;
    ctl.hidden = false;
    go.disabled = true;
    out.textContent = "AI 正在思考，长一点的批改可能需要半分钟到一分钟……";
    abort = new AbortController();
    try {
      const text = await streamAI(kind, body, (t) => (out.textContent = t), abort.signal);
      onDone?.(text);
    } catch (e) {
      if (e.name !== "AbortError") out.textContent = "出错了：" + e.message;
    } finally {
      go.disabled = false;
      ctl.hidden = true;
    }
  };
}
