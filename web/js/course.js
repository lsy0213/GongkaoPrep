// 教程的互动块：课文是 Markdown，夹着若干 “:::类型 参数 … :::” 块，这里把它们渲染成可以操作的组件。
//
// 块类型（写法见 content/course/格式说明.txt）：
//   tip / warn / key / note  提示框（技巧、易错、口诀、说明）
//   quiz      随堂测验（单选 / 多选，选完立即判对错、看解析）
//   example   分步例题（先看题，再一步步展开解法）
//   reveal    想一想（点开看答案）
//   cards     记忆卡（点击翻面；学完本课后自动进“教程知识卡”卡组）
//   fill      填空（输入后检查）
//   order     排序（按顺序点选）
//   match     连线（给左边每项选对应的右边项）
//   drill     速算小练（复用速算训练的题目生成器）
//   calc      计算器（资料分析公式、排列组合、成绩折算）
//   practice  真题演练（从题库按模块 / 题型抽题）
//   write     动笔写（申论小题：作答 → 对照要点自评 → 参考答案 → AI 批改）
//   speak     面试作答（思考 / 作答计时 → 参考思路 → AI 点评）
//   check     清单（勾选状态会保存）
//   flow      流程（横向步骤条）
//   tabs      标签页（--- 标签名 分隔）
//   figure    插图（内容是 SVG / HTML 原样输出）
import { apiPost, esc, fmtClock, LETTERS, md, mountAIBox, shuffle, toast } from "./lib.js";
import { KINDS } from "./pages/speed.js";

// ---------------------------------------------------------------- 解析

export function parseLesson(text) {
  const lines = text.replace(/\r/g, "").split("\n");
  const parts = [];
  let buf = [];
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].match(/^:::\s*([a-z]+)\s*(.*)$/);
    if (!m) { buf.push(lines[i]); continue; }
    if (buf.length) parts.push({ type: "md", body: buf.join("\n") });
    buf = [];
    const body = [];
    i++;
    while (i < lines.length && !/^:::\s*$/.test(lines[i])) body.push(lines[i++]);
    parts.push({ type: m[1], arg: m[2].trim(), body: body.join("\n") });
  }
  if (buf.length) parts.push({ type: "md", body: buf.join("\n") });
  return parts;
}

// 按 “--- 标签” 分段；第一段没有标签
function sections(body) {
  const out = [{ label: "", lines: [] }];
  for (const l of body.split("\n")) {
    const m = l.match(/^---+\s*(.*)$/);
    if (m) out.push({ label: m[1].trim(), lines: [] });
    else out[out.length - 1].lines.push(l);
  }
  return out.map((s) => ({ label: s.label, text: s.lines.join("\n").trim() }));
}

const OPT_RE = /^([A-H])[.．、]\s*(.*)$/;

function parseQuestions(body) {
  return sections(body).filter((s) => s.text).map((s) => {
    const q = { stem: [], options: [], answer: [], explain: [] };
    let mode = "stem";
    for (const l of s.text.split("\n")) {
      let m;
      if (mode !== "explain" && (m = l.match(/^答案[:：]\s*([A-H]+)/))) {
        q.answer = [...m[1]].map((c) => c.charCodeAt(0) - 65);
        mode = "after";
      } else if ((m = l.match(/^解析[:：]\s*(.*)$/))) {
        q.explain.push(m[1]);
        mode = "explain";
      } else if (mode !== "explain" && (m = l.match(OPT_RE))) {
        q.options.push(m[2]);
        mode = "opts";
      } else if (mode === "stem") q.stem.push(l);
      else if (mode === "explain") q.explain.push(l);
      else if (mode === "opts" && l.trim()) q.options[q.options.length - 1] += " " + l.trim();
    }
    return { stem: q.stem.join("\n").trim(), options: q.options, answer: q.answer, explain: q.explain.join("\n").trim() };
  });
}

function pairs(body) {
  return body.split("\n").map((l) => l.split(/\s*::\s*/)).filter((p) => p.length >= 2 && p[0].trim())
    .map(([a, ...b]) => [a.trim().replace(/^[-*]\s+/, ""), b.join(" :: ").trim()]);
}

function items(body) {
  return body.split("\n").filter((l) => /^\s*[-*]\s+/.test(l)).map((l) => l.replace(/^\s*[-*]\s+/, "").trim());
}

function argList(arg) {
  return arg.split("|").map((s) => s.trim());
}

const norm = (s) => String(s).replace(/[\s，,。.、；;：:“”"'‘’（）()]/g, "").toLowerCase();

// 课文里所有记忆卡（服务器也按同样的规则解析，生成“教程知识卡”）
export function lessonCards(parts) {
  return parts.filter((p) => p.type === "cards").flatMap((p) => pairs(p.body));
}

// ---------------------------------------------------------------- 渲染

const CALLOUT = {
  tip: ["技巧", "tip"], warn: ["易错", "warn"], key: ["要记住", "key"], note: ["说明", "note"],
};

// ctx: { lid, st（本课的保存状态）, save(), lesson, course }
export function renderParts(parts, ctx) {
  return parts.map((p, b) => {
    if (p.type === "md") return md(p.body);
    const r = BLOCKS[p.type];
    if (!r) return `<div class="blk blk-unknown small muted">（不认识的块：${esc(p.type)}）</div>`;
    return `<div class="blk blk-${esc(p.type)}" data-b="${b}">${r.html(p, b, ctx)}</div>`;
  }).join("\n");
}

export function bindParts(root, parts, ctx) {
  root.querySelectorAll(".blk[data-b]").forEach((el) => {
    const p = parts[+el.dataset.b];
    const r = BLOCKS[p.type];
    if (r && r.bind) r.bind(el, p, +el.dataset.b, ctx);
  });
}

// 记一次练习结果（同一题以最后一次为准）
function record(ctx, key, ok) {
  ctx.st.quiz = ctx.st.quiz || {};
  ctx.st.quiz[key] = ok ? 1 : 0;
  ctx.save();
  ctx.onScore?.();
}

export function scoreOf(st) {
  const v = Object.values(st?.quiz || {});
  return { n: v.length, ok: v.filter((x) => x).length };
}

const BLOCKS = {};

for (const [k, [label, cls]] of Object.entries(CALLOUT)) {
  BLOCKS[k] = {
    html: (p) => `<div class="callout ${cls}"><div class="callout-h">${esc(p.arg || label)}</div>${md(p.body)}</div>`,
  };
}

// ---- 随堂测验
BLOCKS.quiz = {
  html(p, b) {
    const qs = parseQuestions(p.body);
    return `<div class="blk-title">${esc(p.arg || "随堂练习")}<span class="small muted">${qs.length} 题</span></div>` +
      qs.map((q, i) => `<div class="qz" data-i="${i}">
        <div class="qz-stem">${qs.length > 1 ? `<span class="qz-no">${i + 1}</span>` : ""}${md(q.stem)}</div>
        <div class="qz-opts ${q.options.every((o) => o.length <= 14) && q.options.length === 4 ? "short" : ""}">${q.options.map((o, k) =>
          `<button class="opt" data-k="${k}"><span class="L">${LETTERS[k] || String.fromCharCode(65 + k)}</span><span>${esc(o)}</span></button>`).join("")}</div>
        ${q.answer.length > 1 ? `<div class="row mt"><button class="btn sm" data-confirm>确认（多选）</button></div>` : ""}
        <div class="qz-exp" hidden></div>
      </div>`).join("");
  },
  bind(el, p, b, ctx) {
    const qs = parseQuestions(p.body);
    el.querySelectorAll(".qz").forEach((box) => {
      const q = qs[+box.dataset.i];
      const multi = q.answer.length > 1;
      const chosen = new Set();
      const btns = [...box.querySelectorAll(".opt")];
      const reveal = () => {
        const ok = chosen.size === q.answer.length && q.answer.every((k) => chosen.has(k));
        btns.forEach((x, k) => {
          x.disabled = true;
          x.classList.toggle("right", q.answer.includes(k));
          x.classList.toggle("wrong", chosen.has(k) && !q.answer.includes(k));
          x.classList.remove("chosen");
        });
        const exp = box.querySelector(".qz-exp");
        exp.hidden = false;
        exp.innerHTML = `<div class="row"><span class="verdict ${ok ? "ok" : "no"}">${ok ? "回答正确" : "回答错误"}</span>
          <span class="ink2">答案 <b>${q.answer.map((k) => LETTERS[k] || String.fromCharCode(65 + k)).join("")}</b></span>
          <span class="spacer"></span><button class="btn sm ghost" data-redo>重做</button></div>
          ${q.explain ? `<div class="qz-explain">${md(q.explain)}</div>` : ""}`;
        exp.querySelector("[data-redo]").onclick = () => {
          chosen.clear();
          btns.forEach((x) => { x.disabled = false; x.classList.remove("right", "wrong", "chosen"); });
          exp.hidden = true;
        };
        const cf = box.querySelector("[data-confirm]");
        if (cf) cf.disabled = true;
        record(ctx, `${b}-${box.dataset.i}`, ok);
      };
      btns.forEach((x) => (x.onclick = () => {
        const k = +x.dataset.k;
        if (!multi) { chosen.add(k); reveal(); return; }
        chosen.has(k) ? chosen.delete(k) : chosen.add(k);
        x.classList.toggle("chosen", chosen.has(k));
      }));
      const cf = box.querySelector("[data-confirm]");
      if (cf) cf.onclick = () => { if (chosen.size) { reveal(); cf.disabled = true; } else toast("先选择选项"); };
    });
  },
};

// ---- 分步例题
BLOCKS.example = {
  html(p) {
    const s = sections(p.body);
    const steps = s.slice(1);
    return `<div class="blk-title">${esc(p.arg || "例题")}<span class="small muted">${steps.length} 步</span></div>
      <div class="ex-q">${md(s[0].text)}</div>
      ${steps.map((x, i) => `<div class="ex-step" data-s="${i}" hidden><div class="ex-label">${esc(x.label || `第 ${i + 1} 步`)}</div>${md(x.text)}</div>`).join("")}
      <div class="row mt"><button class="btn sm primary" data-next>先自己想，再看第 1 步</button><button class="btn sm ghost" data-all>全部展开</button></div>`;
  },
  bind(el) {
    const steps = [...el.querySelectorAll(".ex-step")];
    const next = el.querySelector("[data-next]"), all = el.querySelector("[data-all]");
    let n = 0;
    const sync = () => {
      steps.forEach((x, i) => (x.hidden = i >= n));
      next.hidden = all.hidden = n >= steps.length;
      next.textContent = `看第 ${n + 1} 步（共 ${steps.length} 步）`;
    };
    next.onclick = () => { n++; sync(); };
    all.onclick = () => { n = steps.length; sync(); };
    sync();
    if (steps.length) next.textContent = "先自己想，再看第 1 步";
  },
};

// ---- 想一想
BLOCKS.reveal = {
  html(p) {
    const s = sections(p.body);
    const [q, a] = s.length > 1 ? [s[0].text, s.slice(1).map((x) => x.text).join("\n\n")] : ["", s[0].text];
    return `${q ? `<div class="rv-q">${md(q)}</div>` : ""}
      <button class="btn sm" data-show>${esc(p.arg || "想好了，看答案")}</button>
      <div class="rv-a" hidden>${md(a)}</div>`;
  },
  bind(el) {
    const btn = el.querySelector("[data-show]"), a = el.querySelector(".rv-a");
    btn.onclick = () => { a.hidden = !a.hidden; btn.textContent = a.hidden ? "看答案" : "收起"; };
  },
};

// ---- 记忆卡
BLOCKS.cards = {
  html(p) {
    const cs = pairs(p.body);
    return `<div class="blk-title">${esc(p.arg || "记忆卡")}<span class="small muted">${cs.length} 张 · 点卡片翻面</span>
        <span class="spacer"></span><button class="btn sm ghost" data-flipall>全部翻面</button></div>
      <div class="fc-grid">${cs.map(([f, bk]) => `<button class="fc"><span class="fc-f">${esc(f)}</span><span class="fc-b">${esc(bk)}</span></button>`).join("")}</div>
      <p class="small muted" style="margin:6px 0 0">学完本课后，这些卡片会自动加入“闪卡记忆 → 教程知识卡”，按遗忘规律提醒复习。</p>`;
  },
  bind(el) {
    const cards = [...el.querySelectorAll(".fc")];
    cards.forEach((c) => (c.onclick = () => c.classList.toggle("on")));
    let on = false;
    el.querySelector("[data-flipall]").onclick = () => { on = !on; cards.forEach((c) => c.classList.toggle("on", on)); };
  },
};

// ---- 填空
BLOCKS.fill = {
  html(p) {
    const answers = [];
    const text = p.body.replace(/\[\[([^\]]+)\]\]/g, (_m, a) => { answers.push(a); return `⟦${answers.length - 1}⟧`; });
    const html = md(text).replace(/⟦(\d+)⟧/g, (_m, i) => {
      const a = answers[+i].split("|")[0];
      const w = Math.max(3, Math.min(14, [...a].length + 1));
      return `<input class="fill-in" data-i="${i}" style="width:${w * 1.05 + 1.2}em" autocomplete="off" spellcheck="false">`;
    });
    return `<div class="blk-title">${esc(p.arg || "填一填")}<span class="small muted">${answers.length} 空</span></div>
      <div class="fill-body">${html}</div>
      <div class="row mt"><button class="btn sm primary" data-check>检查</button><button class="btn sm ghost" data-ans>看答案</button><span class="small" data-res></span></div>`;
  },
  bind(el, p, b, ctx) {
    const answers = [...p.body.matchAll(/\[\[([^\]]+)\]\]/g)].map((m) => m[1].split("|"));
    const inputs = [...el.querySelectorAll(".fill-in")];
    const check = (record_) => {
      let ok = 0;
      inputs.forEach((x) => {
        const v = x.value.trim();
        const good = !!v && answers[+x.dataset.i].some((a) => a.trim() === v || (norm(a) && norm(a) === norm(v)));
        x.classList.toggle("ok", good);
        x.classList.toggle("no", !good);
        if (!good) x.title = "答案：" + answers[+x.dataset.i][0];
        ok += good ? 1 : 0;
      });
      el.querySelector("[data-res]").innerHTML = ok === inputs.length
        ? `<span class="verdict ok">全对</span>` : `<span class="ink2">对了 ${ok} / ${inputs.length} 空，鼠标移到红框上看答案</span>`;
      if (record_) record(ctx, `${b}`, ok === inputs.length);
    };
    el.querySelector("[data-check]").onclick = () => check(true);
    el.querySelector("[data-ans]").onclick = () => {
      inputs.forEach((x) => { if (!x.classList.contains("ok")) { x.value = answers[+x.dataset.i][0]; x.classList.remove("no"); x.classList.add("shown"); } });
    };
    inputs.forEach((x, i) => (x.onkeydown = (e) => {
      if (e.key === "Enter") { e.preventDefault(); (inputs[i + 1] || el.querySelector("[data-check]")).focus(); }
    }));
  },
};

// ---- 排序
BLOCKS.order = {
  html(p) {
    return `<div class="blk-title">${esc(p.arg || "排一排")}<span class="small muted">按正确顺序依次点击</span></div>
      <div class="ord-ans"></div><div class="ord-pool"></div>
      <div class="row mt"><button class="btn sm primary" data-check>检查</button><button class="btn sm ghost" data-reset>重来</button><span class="small" data-res></span></div>
      <div class="ord-exp" hidden></div>`;
  },
  bind(el, p, b, ctx) {
    const list = items(p.body);
    const exp = (p.body.match(/^解析[:：]\s*([\s\S]*)$/m) || [])[1] || "";
    let pool = shuffle(list.map((t, i) => ({ t, i })));
    if (pool.every((x, k) => x.i === k) && pool.length > 1) pool.reverse();
    let ans = [];
    const draw = () => {
      el.querySelector(".ord-ans").innerHTML = ans.length
        ? ans.map((x, k) => `<button class="ord-item in" data-k="${k}"><b>${k + 1}</b>${esc(x.t)}</button>`).join("")
        : `<div class="small muted">点击下面的选项，按顺序排到这里</div>`;
      el.querySelector(".ord-pool").innerHTML = pool.map((x, k) => `<button class="ord-item" data-k="${k}">${esc(x.t)}</button>`).join("");
      el.querySelectorAll(".ord-pool .ord-item").forEach((x) => (x.onclick = () => { ans.push(pool.splice(+x.dataset.k, 1)[0]); draw(); }));
      el.querySelectorAll(".ord-ans .ord-item").forEach((x) => (x.onclick = () => { pool.push(ans.splice(+x.dataset.k, 1)[0]); draw(); }));
    };
    el.querySelector("[data-reset]").onclick = () => { pool = shuffle(list.map((t, i) => ({ t, i }))); ans = []; el.querySelector(".ord-exp").hidden = true; el.querySelector("[data-res]").innerHTML = ""; draw(); };
    el.querySelector("[data-check]").onclick = () => {
      if (pool.length) { toast("还有选项没排进去"); return; }
      const ok = ans.every((x, k) => x.i === k);
      el.querySelector("[data-res]").innerHTML = ok ? `<span class="verdict ok">顺序正确</span>` : `<span class="verdict no">不对</span>`;
      const e = el.querySelector(".ord-exp");
      e.hidden = false;
      e.innerHTML = `<b class="small">正确顺序</b><ol class="small">${list.map((t) => `<li>${esc(t)}</li>`).join("")}</ol>${exp ? md(exp) : ""}`;
      record(ctx, `${b}`, ok);
    };
    draw();
  },
};

// ---- 连线
BLOCKS.match = {
  html(p) {
    const ps = pairs(p.body);
    const rights = shuffle([...new Set(ps.map((x) => x[1]))]);
    return `<div class="blk-title">${esc(p.arg || "连一连")}<span class="small muted">给左边每一项选出对应的右边项</span></div>
      <div class="mt-grid">${ps.map(([l], i) => `<div class="mt-l">${esc(l)}</div>
        <select data-i="${i}"><option value="">请选择…</option>${rights.map((r) => `<option>${esc(r)}</option>`).join("")}</select><span class="mt-r" data-r="${i}"></span>`).join("")}</div>
      <div class="row mt"><button class="btn sm primary" data-check>检查</button><button class="btn sm ghost" data-ans>看答案</button><span class="small" data-res></span></div>`;
  },
  bind(el, p, b, ctx) {
    const ps = pairs(p.body);
    const sels = [...el.querySelectorAll("select")];
    el.querySelector("[data-check]").onclick = () => {
      let ok = 0;
      sels.forEach((s) => {
        const good = s.value === ps[+s.dataset.i][1];
        ok += good ? 1 : 0;
        el.querySelector(`[data-r="${s.dataset.i}"]`).innerHTML = s.value ? (good ? `<span style="color:var(--good)">✓</span>` : `<span style="color:var(--bad)">✗</span>`) : "";
      });
      el.querySelector("[data-res]").innerHTML = ok === ps.length ? `<span class="verdict ok">全对</span>` : `<span class="ink2">对了 ${ok} / ${ps.length}</span>`;
      record(ctx, `${b}`, ok === ps.length);
    };
    el.querySelector("[data-ans]").onclick = () => {
      sels.forEach((s) => { s.value = ps[+s.dataset.i][1]; el.querySelector(`[data-r="${s.dataset.i}"]`).innerHTML = ""; });
    };
  },
};

// ---- 速算小练
BLOCKS.drill = {
  html(p) {
    const [kind, n] = argList(p.arg);
    const k = KINDS[kind];
    return `<div class="blk-title">速算小练：${esc(k ? k.name : kind)}<span class="small muted">${n || 10} 题 · ${esc(k ? k.hint : "")}</span></div>
      ${p.body.trim() ? md(p.body) : ""}
      <div class="dr-box"><button class="btn sm primary" data-go>开始</button></div>`;
  },
  bind(el, p, b, ctx) {
    const [kind, n0] = argList(p.arg);
    const k = KINDS[kind];
    if (!k) return;
    const total = +(n0 || 10);
    const box = el.querySelector(".dr-box");
    const start = () => {
      let i = 0, ok = 0;
      const t0 = Date.now();
      const next = () => {
        if (i >= total) {
          const sec = Math.round((Date.now() - t0) / 1000);
          box.innerHTML = `<div class="row"><span class="verdict ${ok >= total * 0.8 ? "ok" : "no"}">${ok} / ${total}</span>
            <span class="ink2">用时 ${fmtClock(sec)}，平均每题 ${(sec / total).toFixed(1)} 秒</span>
            <button class="btn sm" data-go>再来一轮</button><a class="btn sm ghost" href="#/speed">去速算训练</a></div>`;
          box.querySelector("[data-go]").onclick = start;
          record(ctx, `${b}`, ok >= total * 0.8);
          return;
        }
        const q = k.make();
        box.innerHTML = `<div class="dr-q"><span class="small muted">${i + 1}/${total}</span><b>${esc(q.q).replace(/\n/g, "<br>")}</b></div>
          <div class="drill-opts">${q.options.map((o) => `<button data-o="${esc(o)}">${esc(o)}</button>`).join("")}</div>`;
        box.querySelectorAll("[data-o]").forEach((x) => (x.onclick = () => {
          const good = x.dataset.o === q.answer;
          ok += good ? 1 : 0;
          box.querySelectorAll("[data-o]").forEach((y) => {
            y.disabled = true;
            if (y.dataset.o === q.answer) y.classList.add("right");
            else if (y === x) y.classList.add("wrong");
          });
          i++;
          setTimeout(next, good ? 350 : 1100);
        }));
      };
      next();
    };
    box.querySelector("[data-go]").onclick = start;
  },
};

// ---- 计算器
const CALCS = {
  growth: {
    name: "增长计算器：已知现期量和增长率",
    fields: [["A", "现期量", 5280], ["r", "增长率 %", 12.4]],
    out(v) {
      const r = v.r / 100, base = v.A / (1 + r), inc = v.A - base, n = Math.round(100 / v.r);
      return [
        ["基期量 = 现期 ÷ (1 + r)", base.toFixed(2)],
        ["增长量 = 现期 − 基期 = 现期 × r ÷ (1 + r)", inc.toFixed(2)],
        [`估算：r ≈ 1/${n}（${(100 / n).toFixed(1)}%）时，增长量 ≈ 现期 ÷ ${n + 1}`, (v.A / (n + 1)).toFixed(2)],
      ];
    },
  },
  annual: {
    name: "年均增长率计算器",
    fields: [["B", "初期量", 1000], ["A", "末期量", 1480], ["n", "间隔年数", 4]],
    out(v) {
      const exact = (Math.pow(v.A / v.B, 1 / v.n) - 1) * 100;
      return [
        ["年均增长率 = (末期 ÷ 初期)^(1/n) − 1", exact.toFixed(2) + "%"],
        ["总增长率 ÷ n（估算上限，实际比它小）", (((v.A / v.B) - 1) / v.n * 100).toFixed(2) + "%"],
        ["年均增长量 = (末期 − 初期) ÷ n", ((v.A - v.B) / v.n).toFixed(2)],
      ];
    },
  },
  interval: {
    name: "间隔增长率计算器",
    fields: [["r1", "今年增长率 %", 8.5], ["r2", "去年增长率 %", 6.2]],
    out(v) {
      const r = v.r1 + v.r2 + (v.r1 * v.r2) / 100;
      return [["间隔增长率 = r1 + r2 + r1 × r2", r.toFixed(2) + "%"], ["其中 r1 × r2 这一项", ((v.r1 * v.r2) / 100).toFixed(2) + "%"]];
    },
  },
  share: {
    name: "比重计算器：现期比重、基期比重与变化",
    fields: [["A", "部分（现期）", 860], ["a", "部分增长率 %", 15], ["B", "整体（现期）", 5200], ["b", "整体增长率 %", 8]],
    out(v) {
      const a = v.a / 100, b = v.b / 100, now = v.A / v.B, base = now * (1 + b) / (1 + a);
      return [
        ["现期比重 = A ÷ B", (now * 100).toFixed(2) + "%"],
        ["基期比重 = A/B × (1+b)/(1+a)", (base * 100).toFixed(2) + "%"],
        ["比重变化 = A/B × (a−b)/(1+a)（百分点）", ((now - base) * 100).toFixed(2) + " 个百分点"],
        ["判断升降：只看 a 与 b", a > b ? "a > b，比重上升" : a < b ? "a < b，比重下降" : "a = b，比重不变"],
      ];
    },
  },
  average: {
    name: "平均数计算器",
    fields: [["A", "总量（现期）", 7200], ["a", "总量增长率 %", 10], ["B", "份数（现期）", 240], ["b", "份数增长率 %", 4]],
    out(v) {
      const a = v.a / 100, b = v.b / 100;
      return [
        ["现期平均数 = A ÷ B", (v.A / v.B).toFixed(2)],
        ["基期平均数 = A/B × (1+b)/(1+a)", (v.A / v.B * (1 + b) / (1 + a)).toFixed(2)],
        ["平均数增长率 = (a − b) ÷ (1 + b)", (((a - b) / (1 + b)) * 100).toFixed(2) + "%"],
      ];
    },
  },
  perm: {
    name: "排列组合计算器",
    fields: [["n", "总数 n", 6], ["m", "选出 m", 3]],
    out(v) {
      const n = Math.round(v.n), m = Math.round(v.m);
      if (m > n || m < 0 || n > 30) return [["提示", "需要 0 ≤ m ≤ n ≤ 30"]];
      let A = 1;
      for (let i = 0; i < m; i++) A *= n - i;
      let f = 1;
      for (let i = 2; i <= m; i++) f *= i;
      return [[`排列 A(${n},${m}) = ${n}×${n - 1}×…（乘 ${m} 个数）`, A.toLocaleString()],
        [`组合 C(${n},${m}) = A(${n},${m}) ÷ ${m}!`, (A / f).toLocaleString()],
        [`${m}! = ${m} 个人的全排列`, f.toLocaleString()]];
    },
  },
  score: {
    name: "四川省考成绩折算",
    fields: [["x", "行测", 70], ["s", "申论", 65], ["m", "面试", 80], ["w", "笔试占比（50 或 60）", 50]],
    out(v) {
      const w = v.w >= 55 ? 0.6 : 0.5, half = w / 2;
      const written = v.x * half + v.s * half, total = written + v.m * (1 - w);
      return [
        [`笔试成绩 = 行测 × ${half * 100}% + 申论 × ${half * 100}%（不含加分）`, written.toFixed(2)],
        [`总成绩 = 笔试成绩 + 面试 × ${(1 - w) * 100}%`, total.toFixed(2)],
        ["面试每多 1 分，总成绩多", (1 - w).toFixed(1) + " 分"],
        ["笔试（行测或申论）每多 1 分，总成绩多", half.toFixed(2) + " 分"],
      ];
    },
  },
};

BLOCKS.calc = {
  html(p) {
    const c = CALCS[p.arg];
    if (!c) return `<div class="small muted">未知计算器 ${esc(p.arg)}</div>`;
    return `<div class="blk-title">${esc(c.name)}<span class="small muted">改数字，结果实时变化</span></div>
      ${p.body.trim() ? md(p.body) : ""}
      <div class="calc-in">${c.fields.map(([k, l, d]) => `<label class="field">${esc(l)}<input type="number" step="any" data-f="${k}" value="${d}"></label>`).join("")}</div>
      <div class="calc-out"></div>`;
  },
  bind(el, p) {
    const c = CALCS[p.arg];
    if (!c) return;
    const run = () => {
      const v = {};
      el.querySelectorAll("[data-f]").forEach((x) => (v[x.dataset.f] = parseFloat(x.value) || 0));
      el.querySelector(".calc-out").innerHTML = c.out(v).map(([k, val]) => `<div class="calc-row"><span>${esc(k)}</span><b class="num">${esc(val)}</b></div>`).join("");
    };
    el.querySelectorAll("[data-f]").forEach((x) => (x.oninput = run));
    run();
  },
};

// ---- 真题演练
BLOCKS.practice = {
  html(p) {
    const [module, sub = "", count = "10", src = "all"] = argList(p.arg);
    const q = new URLSearchParams({ module, count, auto: "1" });
    if (sub && sub !== "全部") q.set("sub", sub);
    if (src && src !== "all") q.set("src", src);
    return `<div class="pr-card">
      <div class="pr-ico">✎</div>
      <div class="pr-body"><b>真题演练：${esc(sub && sub !== "全部" ? sub : module)} · ${esc(count)} 题</b>
        <div class="small ink2">${p.body.trim() ? esc(p.body.trim()) : "学完方法马上用真题检验，做错的题自动进错题本。"}</div>
        <div class="small muted" data-avail></div></div>
      <a class="btn primary" href="#/practice?${q}">开始练习</a></div>`;
  },
  bind(el, p) {
    const [module, sub = "", , src = "all"] = argList(p.arg);
    apiPost("/api/bank/summary", { module, sub: sub || "全部", src }).then((s) => {
      const t = el.querySelector("[data-avail]");
      if (t) t.textContent = s.matching ? `题库里有 ${s.matching} 道，你做过 ${s.matching_done} 道` : "题库里还没有这类题（可以先到资料库整理真题）";
    }).catch(() => {});
  },
};

// ---- 动笔写（申论）
BLOCKS.write = {
  html(p, b, ctx) {
    const [title, words = "", score = ""] = argList(p.arg);
    const s = sections(p.body);
    const pts = s.find((x) => /要点/.test(x.label));
    const ref = s.find((x) => /参考|示范/.test(x.label));
    const draft = ctx.st.drafts?.[b] || "";
    return `<div class="blk-title">动笔写：${esc(title || "练一练")}<span class="small muted">${words ? `${esc(words)} 字以内` : ""}${score ? ` · ${esc(score)} 分` : ""}</span></div>
      <div class="wr-q">${md(s[0].text)}</div>
      <textarea class="wr-text" rows="7" placeholder="在这里作答（会自动保存）">${esc(draft)}</textarea>
      <div class="row small"><span class="muted" data-count></span><span class="spacer"></span>
        ${pts ? `<button class="btn sm" data-pts>对照要点自评</button>` : ""}${ref ? `<button class="btn sm ghost" data-ref>看参考答案</button>` : ""}</div>
      ${pts ? `<div class="wr-pts" hidden><div class="small ink2 mb">勾出你答到的要点（意思对即可）：</div>
        ${items(pts.text).map((x, i) => `<label class="wr-pt"><input type="checkbox" data-pt="${i}"> <span>${esc(x)}</span></label>`).join("")}
        <div class="small mt" data-ptres></div></div>` : ""}
      ${ref ? `<div class="wr-ref" hidden>${md(ref.text)}</div>` : ""}
      <div class="mt" data-ai></div>`;
  },
  bind(el, p, b, ctx) {
    const [title, words = "", score = ""] = argList(p.arg);
    const s = sections(p.body);
    const pts = s.find((x) => /要点/.test(x.label));
    const ref = s.find((x) => /参考|示范/.test(x.label));
    const ta = el.querySelector(".wr-text");
    const cnt = () => {
      const n = ta.value.replace(/\s/g, "").length;
      el.querySelector("[data-count]").textContent = `${n} 字${words && n > +words ? `（超出 ${n - +words} 字）` : ""}`;
    };
    let t = null;
    ta.oninput = () => {
      cnt();
      clearTimeout(t);
      t = setTimeout(() => { ctx.st.drafts = ctx.st.drafts || {}; ctx.st.drafts[b] = ta.value; ctx.save(); }, 600);
    };
    cnt();
    const pb = el.querySelector("[data-pts]");
    if (pb) pb.onclick = () => { el.querySelector(".wr-pts").hidden = false; pb.hidden = true; };
    const boxes = [...el.querySelectorAll("[data-pt]")];
    boxes.forEach((x) => (x.onchange = () => {
      const n = boxes.filter((y) => y.checked).length;
      el.querySelector("[data-ptres]").innerHTML = `答到 ${n} / ${boxes.length} 个要点${score ? `，按点给分约 ${Math.round((n / boxes.length) * +score)} / ${score} 分` : ""}`;
      record(ctx, `${b}`, n >= boxes.length * 0.7);
    }));
    const rb = el.querySelector("[data-ref]");
    if (rb) rb.onclick = () => { const r = el.querySelector(".wr-ref"); r.hidden = !r.hidden; rb.textContent = r.hidden ? "看参考答案" : "收起参考答案"; };
    mountAIBox(el.querySelector("[data-ai]"), {
      label: "请 AI 批改",
      kind: "essay",
      getBody: () => ({
        materials: s[0].text, question: title, requirement: s[0].text.slice(0, 300), score: score || "—", words: words || "不限",
        points: pts ? items(pts.text) : [], reference: ref ? ref.text : "", answer: ta.value,
      }),
    });
  },
};

// ---- 面试作答
BLOCKS.speak = {
  html(p) {
    const s = sections(p.body);
    const guide = s.slice(1).map((x) => (x.label ? `**${x.label}**\n\n` : "") + x.text).join("\n\n");
    return `<div class="blk-title">开口练：${esc(p.arg || "面试题")}<span class="small muted">思考 1 分钟 · 作答 3 分钟</span></div>
      <div class="sp-q">${md(s[0].text)}</div>
      <div class="row"><span class="clock" data-clock>01:00</span><span class="small ink2" data-phase>准备好后点开始，先思考 1 分钟</span><span class="spacer"></span>
        <button class="btn sm primary" data-go>开始思考</button><button class="btn sm ghost" data-stop hidden>结束</button></div>
      <textarea class="sp-note" rows="4" placeholder="边想边记要点；作答后可以把你说的内容大致写下来，请 AI 点评"></textarea>
      ${guide ? `<div class="row small"><span class="spacer"></span><button class="btn sm ghost" data-guide>看参考思路</button></div><div class="sp-guide" hidden>${md(guide)}</div>` : ""}
      <div class="mt" data-ai></div>`;
  },
  bind(el, p, b, ctx) {
    const s = sections(p.body);
    const guide = s.slice(1).map((x) => x.text).join("\n");
    const clock = el.querySelector("[data-clock]"), phase = el.querySelector("[data-phase]");
    const go = el.querySelector("[data-go]"), stop = el.querySelector("[data-stop]");
    let timer = null, left = 60, stage = 0;
    const tick = () => {
      left--;
      clock.textContent = fmtClock(Math.max(0, left));
      clock.classList.toggle("low", left <= 15);
      if (left > 0) return;
      clearInterval(timer);
      if (stage === 1) {
        stage = 2; left = 180;
        phase.textContent = "开始作答（出声说！），3 分钟";
        timer = setInterval(tick, 1000);
      } else end();
    };
    const end = () => {
      clearInterval(timer);
      stage = 0;
      phase.textContent = "结束。对照参考思路，看看漏了什么";
      go.hidden = false; go.textContent = "再练一次"; stop.hidden = true;
      record(ctx, `${b}`, true);
    };
    go.onclick = () => {
      stage = 1; left = 60; clock.textContent = "01:00";
      phase.textContent = "思考中：先定题型和框架，记下 3 个要点";
      go.hidden = true; stop.hidden = false;
      clearInterval(timer);
      timer = setInterval(tick, 1000);
    };
    stop.onclick = end;
    const gb = el.querySelector("[data-guide]");
    if (gb) gb.onclick = () => { const g = el.querySelector(".sp-guide"); g.hidden = !g.hidden; gb.textContent = g.hidden ? "看参考思路" : "收起参考思路"; };
    mountAIBox(el.querySelector("[data-ai]"), {
      label: "请 AI 点评我的作答",
      kind: "interview",
      getBody: () => ({ type: p.arg, question: s[0].text, guide, answer: el.querySelector(".sp-note").value }),
    });
    ctx.cleanups.push(() => clearInterval(timer));
  },
};

// ---- 清单
BLOCKS.check = {
  html(p, b, ctx) {
    const list = items(p.body);
    const st = ctx.st.check?.[b] || {};
    return `<div class="blk-title">${esc(p.arg || "清单")}<span class="small muted" data-cnt></span></div>
      <div class="checklist">${list.map((x, i) => `<label><input type="checkbox" data-c="${i}" ${st[i] ? "checked" : ""}> <span>${md(x).replace(/^<p>|<\/p>$/g, "")}</span></label>`).join("")}</div>`;
  },
  bind(el, p, b, ctx) {
    const boxes = [...el.querySelectorAll("[data-c]")];
    const cnt = () => (el.querySelector("[data-cnt]").textContent = `已完成 ${boxes.filter((x) => x.checked).length} / ${boxes.length}`);
    boxes.forEach((x) => (x.onchange = () => {
      ctx.st.check = ctx.st.check || {};
      ctx.st.check[b] = Object.fromEntries(boxes.map((y, i) => [i, y.checked]));
      ctx.save();
      cnt();
    }));
    cnt();
  },
};

// ---- 流程
BLOCKS.flow = {
  html(p) {
    const ps = pairs(p.body);
    return `${p.arg ? `<div class="blk-title">${esc(p.arg)}</div>` : ""}
      <ol class="flow">${ps.map(([t, d], i) => `<li><span class="flow-n">${i + 1}</span><b>${esc(t)}</b><span>${esc(d)}</span></li>`).join("")}</ol>`;
  },
};

// ---- 标签页
BLOCKS.tabs = {
  html(p) {
    const s = sections(p.body).filter((x) => x.label);
    return `${p.arg ? `<div class="blk-title">${esc(p.arg)}</div>` : ""}
      <div class="tabs tb-head">${s.map((x, i) => `<button data-t="${i}" class="${i ? "" : "active"}">${esc(x.label)}</button>`).join("")}</div>
      ${s.map((x, i) => `<div class="tb-body" data-t="${i}" ${i ? "hidden" : ""}>${md(x.text)}</div>`).join("")}`;
  },
  bind(el) {
    el.querySelectorAll(".tb-head button").forEach((x) => (x.onclick = () => {
      el.querySelectorAll(".tb-head button").forEach((y) => y.classList.toggle("active", y === x));
      el.querySelectorAll(".tb-body").forEach((y) => (y.hidden = y.dataset.t !== x.dataset.t));
    }));
  },
};

// ---- 插图（课文作者写的 SVG，原样输出）
BLOCKS.figure = {
  html(p) {
    return `<figure class="fig">${p.body}${p.arg ? `<figcaption>${esc(p.arg)}</figcaption>` : ""}</figure>`;
  },
};
