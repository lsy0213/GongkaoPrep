import { apiGet, apiPost, content, esc, fmtClock, shuffle, store, toast } from "../lib.js";

const ROUND = 20;
const rnd = (a, b) => a + Math.floor(Math.random() * (b - a + 1));

function spread(v, fmt, deltas = [-0.12, -0.06, 0.07, 0.14]) {
  const picks = shuffle(deltas).slice(0, 3);
  const opts = new Set([fmt(v)]);
  for (const d of picks) opts.add(fmt(v * (1 + d)));
  let k = 0.2;
  while (opts.size < 4) opts.add(fmt(v * (1 + (k += 0.05))));
  return shuffle([...opts]);
}

// 百分数答案的选项：先放易错项（traps，比如隔年增长率漏掉 r1×r2），再按百分点上下错开
const pct = (x) => x.toFixed(1) + "%";
function pctOpts(v, traps = []) {
  const vals = [v];
  const add = (x) => { if (vals.length < 4 && vals.every((y) => Math.abs(x - y) >= 0.8)) vals.push(x); };
  traps.forEach(add);
  shuffle([-3, -1.6, 1.6, 3, -4.5, 4.5, -6, 6]).forEach((d) => add(v + d));
  return shuffle(vals.map(pct));
}
const signed = (x) => (x < 0 ? "−" + Math.abs(x) : String(x));

// 口算基本功：题目来自《新速算》练习册（tools/build_speed.py 生成 content/speed_bank.json），
// 按期顺序往下练，进度存在 prefs 的 speed_pos 里。input = 自己输入答案，不给选项。
export const BANK_KINDS = {
  m21: {
    name: "两位数×一位数", hint: "口算，40 组 1.5 分钟达标", input: true,
    make([a, b]) {
      const t = Math.floor(a / 10) * 10, u = a % 10;
      return { q: `${a} × ${b}`, answer: String(a * b),
        explain: u ? `${t}×${b} + ${u}×${b} = ${t * b} + ${u * b} = ${a * b}` : `${a} × ${b} = ${a * b}` };
    },
  },
  as2: {
    name: "两位数加减", hint: "口算，20 组 2 分钟达标", input: true,
    make([a, b, s]) {
      const v = s > 0 ? a + b : a - b;
      return { q: `${a} ${s > 0 ? "+" : "−"} ${b}`, answer: String(v), explain: `${a} ${s > 0 ? "+" : "−"} ${b} = ${signed(v)}` };
    },
  },
  as3: {
    name: "三位数加减", hint: "口算，20 组 3 分钟达标", input: true,
    make([a, b, s]) {
      const v = s > 0 ? a + b : a - b;
      return { q: `${a} ${s > 0 ? "+" : "−"} ${b}`, answer: String(v), explain: `${a} ${s > 0 ? "+" : "−"} ${b} = ${signed(v)}` };
    },
  },
  d2: {
    name: "除以两位数 · 商首位", hint: "只要商的第一位，不四舍五入", input: true,
    make([a, b]) {
      const q = Math.floor(a / b);
      return { q: `${a} ÷ ${b}\n商的首位 =`, answer: String(q)[0], explain: `${a} ÷ ${b} = ${q}…，首位是 ${String(q)[0]}` };
    },
  },
  d3: {
    name: "除以三位数 · 商前两位", hint: "只要商的前两位，不四舍五入", input: true,
    make([a, b]) {
      const q = Math.floor(a / b);
      return { q: `${a} ÷ ${b}\n商的前两位 =`, answer: String(q).slice(0, 2), explain: `${a} ÷ ${b} = ${(a / b).toFixed(2)}，前两位是 ${String(q).slice(0, 2)}` };
    },
  },
  d4: {
    name: "四位数除法 · 看选项截位", hint: "根据选项差距决定截几位，20 题 4 分钟优秀",
    make([a, b, o1, o2, o3, o4, k]) {
      const opts = [o1, o2, o3, o4];
      return { q: `${a} ÷ ${b} ≈`, answer: opts[k], options: opts, explain: `${a} ÷ ${b} = ${(a / b).toFixed(3)}` };
    },
  },
};

export const KINDS = {
  mul: {
    name: "两位数乘法", hint: "精确计算，练基本功",
    make() {
      const a = rnd(12, 98), b = rnd(12, 98), v = a * b;
      const opts = shuffle([...new Set([v, v + 10, v - 10, v + a, v - b, v + 100].filter((x) => x > 0))].slice(0, 6)).slice(0, 4);
      if (!opts.includes(v)) opts[0] = v;
      return { q: `${a} × ${b}`, answer: String(v), options: shuffle(opts.map(String)), explain: `${a} × ${b} = ${v}` };
    },
  },
  div: {
    name: "除法估算", hint: "选最接近的结果，练截位直除",
    make() {
      const a = rnd(1200, 98000), b = rnd(13, 97), v = a / b;
      const fmt = (x) => (x >= 100 ? Math.round(x).toString() : x.toFixed(1));
      return { q: `${a} ÷ ${b} ≈`, answer: fmt(v), options: spread(v, fmt), explain: `${a} ÷ ${b} = ${v.toFixed(2)}` };
    },
  },
  base: {
    name: "基期计算", hint: "现期 ÷ (1 + r)",
    make() {
      const now = rnd(800, 9800) * (Math.random() < 0.5 ? 1 : 10), r = rnd(21, 189) / 10;
      const v = now / (1 + r / 100);
      const fmt = (x) => Math.round(x).toString();
      return { q: `现期 ${now}，增长 ${r}%\n基期 ≈`, answer: fmt(v), options: spread(v, fmt, [-0.09, -0.05, 0.05, 0.09]),
        explain: `基期 = ${now} ÷ ${+(1 + r / 100).toFixed(3)} = ${v.toFixed(1)}` };
    },
  },
  inc: {
    name: "增长量计算", hint: "r ≈ 1/n 时，增长量 ≈ 现期 ÷ (n+1)",
    make() {
      const n = rnd(3, 12), r = +(100 / n + (Math.random() - 0.5) * 1.2).toFixed(1);
      const now = rnd(300, 9900);
      const v = (now / (1 + r / 100)) * (r / 100);
      const fmt = (x) => (x >= 100 ? Math.round(x).toString() : x.toFixed(1));
      return { q: `现期 ${now}，增长 ${r}%\n增长量 ≈`, answer: fmt(v), options: spread(v, fmt, [-0.18, -0.1, 0.1, 0.18]),
        explain: `${r}% ≈ 1/${n}，增长量 ≈ ${now} ÷ ${n + 1} = ${(now / (n + 1)).toFixed(1)}（精确值 ${v.toFixed(1)}）` };
    },
  },
  share: {
    name: "比重计算", hint: "部分 ÷ 整体，结果用百分数",
    make() {
      const whole = rnd(2000, 99000), part = Math.round(whole * rnd(8, 82) / 100 * (0.9 + Math.random() * 0.2));
      const v = (part / whole) * 100;
      const fmt = (x) => x.toFixed(1) + "%";
      const opts = new Set([fmt(v)]);
      for (const d of shuffle([-6, -3, 3, 6, -9, 9])) { if (opts.size >= 4) break; if (v + d > 0) opts.add(fmt(v + d)); }
      return { q: `${part} ÷ ${whole} ≈`, answer: fmt(v), options: shuffle([...opts]), explain: `${part} ÷ ${whole} = ${v.toFixed(2)}%` };
    },
  },
  frac: {
    name: "百化分", hint: "记熟常用分数对应的百分数",
    make() {
      const table = [[2, 50], [3, 33.3], [4, 25], [5, 20], [6, 16.7], [7, 14.3], [8, 12.5], [9, 11.1], [11, 9.1], [12, 8.3], [13, 7.7], [14, 7.1], [15, 6.7], [16, 6.3], [17, 5.9], [18, 5.6], [19, 5.3]];
      const [n, p] = table[rnd(0, table.length - 1)];
      const others = shuffle(table.filter((x) => x[0] !== n)).slice(0, 3).map((x) => x[1] + "%");
      const explain = `1/${n} = ${(100 / n).toFixed(2)}%`;
      return Math.random() < 0.5
        ? { q: `1/${n} ≈`, answer: p + "%", options: shuffle([p + "%", ...others]), explain }
        : { q: `${p}% ≈`, answer: `1/${n}`, options: shuffle([`1/${n}`, ...shuffle(table.filter((x) => x[0] !== n)).slice(0, 3).map((x) => "1/" + x[0])]), explain };
    },
  },
  rate: {
    name: "增长率计算", hint: "(现期 − 基期) ÷ 基期",
    make() {
      const base = rnd(500, 9800), now = Math.round(base * (1 + rnd(-150, 450) / 1000));
      const v = (now / base - 1) * 100;
      return { q: `现期 ${now}，基期 ${base}\n增长率 ≈`, answer: pct(v), options: pctOpts(v, [((now - base) / now) * 100]),
        explain: `(${now} − ${base}) ÷ ${base} = ${signed(now - base)} ÷ ${base} = ${v.toFixed(2)}%（注意除以基期，不是现期）` };
    },
  },
  gap: {
    name: "隔年增长率", hint: "r₁ + r₂ + r₁ × r₂",
    make() {
      const r1 = rnd(-60, 260) / 10, r2 = rnd(-60, 260) / 10;
      const v = r1 + r2 + (r1 * r2) / 100;
      return { q: `今年增长 ${r1}%，去年增长 ${r2}%\n比前年增长 ≈`, answer: pct(v), options: pctOpts(v, [r1 + r2]),
        explain: `${r1}% + ${r2}% + ${r1}% × ${r2}% = ${(r1 + r2).toFixed(1)}% + ${(r1 * r2 / 100).toFixed(2)}% = ${v.toFixed(2)}%` };
    },
  },
  avg: {
    name: "平均数增长率", hint: "(a − b) ÷ (1 + b)",
    make() {
      const a = rnd(-40, 300) / 10, b = rnd(-40, 200) / 10;
      const v = ((a - b) / (100 + b)) * 100;
      return { q: `总量增长 ${a}%，个数增长 ${b}%\n平均数增长 ≈`, answer: pct(v), options: pctOpts(v, [a - b, (a - b) / (1 + a / 100)]),
        explain: `(${a}% − ${b}%) ÷ (1 + ${b}%) = ${(a - b).toFixed(1)}% ÷ ${(1 + b / 100).toFixed(3)} = ${v.toFixed(2)}%` };
    },
  },
  pmul: {
    name: "百分数乘法", hint: "整体 × 比重，取前两三位估算",
    make() {
      const A = rnd(1200, 98000), r = rnd(51, 899) / 10, v = (A * r) / 100;
      const fmt = (x) => (x >= 100 ? Math.round(x).toString() : x.toFixed(1));
      return { q: `${A} × ${r}% ≈`, answer: fmt(v), options: spread(v, fmt), explain: `${A} × ${r}% = ${v.toFixed(1)}` };
    },
  },
  mul3: {
    name: "三位数乘法估算", hint: "截位相乘，误差控制在 5% 以内",
    make() {
      const a = rnd(102, 998), b = rnd(102, 998), v = a * b;
      const fmt = (x) => Math.round(x).toString();
      return { q: `${a} × ${b} ≈`, answer: fmt(v), options: spread(v, fmt, [-0.15, -0.08, 0.08, 0.15]),
        explain: `${a} × ${b} = ${v}，可估 ${Math.round(a / 10)}0 × ${b} ≈ ${Math.round(a / 10) * 10 * b}` };
    },
  },
};

const kindOf = (k) => BANK_KINDS[k] || KINDS[k];
// 输入的答案：去掉空格逗号，各种减号统一成 "-"
const norm = (s) => String(s).replace(/[\s,，]/g, "").replace(/[−—－–]/g, "-").replace(/^\+/, "");
const fmtN = (n) => n.toLocaleString("en-US");

export async function render(el) {
  let records = (await apiGet("/api/stats")).speed;
  let bank = null;
  try { bank = await content("speed_bank.json"); } catch { /* 没有题库文件时只显示随机题 */ }
  let tick = null, keyHandler = null;

  const pos = (k) => (store.get("speed_pos", {})[k] || 0);
  // 第 n 题属于第几期
  const issueOf = (k, n) => {
    const days = bank.kinds[k].days;
    let d = days[0][0];
    for (const [day, start] of days) { if (start > n) break; d = day; }
    return d;
  };

  function deck(k, v) {
    const mine = records.filter((r) => r.kind === k);
    const best = mine.slice().sort((a, z) => z.correct / z.total - a.correct / a.total || a.seconds - z.seconds)[0];
    let count = `<span class="small muted">随机出题 · 题量不限</span>`;
    if (BANK_KINDS[k]) {
      const n = bank.kinds[k].items.length, p = pos(k);
      count = `<span class="small muted num">共 ${fmtN(n)} 题 · 已练 ${fmtN(p)} 题 · 下一轮第 ${issueOf(k, p)} 期</span>
        <span class="sp-bar"><i style="width:${Math.max(p ? 1 : 0, (p / n) * 100).toFixed(1)}%"></i></span>`;
    }
    return `<button class="deck" data-k="${k}"><b>${esc(v.name)}</b><span class="small ink2">${esc(v.hint)}</span>${count}
      <span class="small muted">${best ? `最好成绩：${best.correct}/${best.total}，${fmtClock(best.seconds)}` : "还没练过"}${mine.length ? ` · 最近练过 ${mine.length} 轮` : ""}</span></button>`;
  }

  function home() {
    const total = bank ? Object.values(bank.kinds).reduce((s, x) => s + x.items.length, 0) : 0;
    el.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">速算训练</div><h1>每天 10 分钟，资料分析快一半</h1>
        <p>每轮 ${ROUND} 题。目标：正确率 90% 以上，平均每题 6 秒以内。</p></div>
        <a class="btn" href="#/learn/data">资料分析教程</a></div>
      ${bank ? `<div class="sp-sec"><h2>口算基本功</h2><span class="small muted">${esc(bank.source)}，共 ${fmtN(total)} 题，按期顺序往下练；前五项自己输入答案</span></div>
      <div class="grid cols-3">${Object.entries(BANK_KINDS).map(([k, v]) => deck(k, v)).join("")}</div>` : ""}
      <div class="sp-sec"><h2>资料分析公式</h2><span class="small muted">每轮随机出题，题量不限，选最接近的答案</span></div>
      <div class="grid cols-3">${Object.entries(KINDS).map(([k, v]) => deck(k, v)).join("")}</div>
      ${records.length ? `<div class="card mt"><h3 class="mb">最近记录</h3><div class="table-wrap"><table class="tbl">
        <thead><tr><th>时间</th><th>项目</th><th class="n">正确</th><th class="n">用时</th><th class="n">平均每题</th></tr></thead><tbody>
        ${records.slice(0, 10).map((r) => `<tr><td class="small">${esc(r.created_at.slice(5, 16))}</td><td>${esc(kindOf(r.kind)?.name || r.kind)}</td>
          <td class="n">${r.correct}/${r.total}</td><td class="n">${fmtClock(r.seconds)}</td><td class="n">${(r.seconds / r.total).toFixed(1)} 秒</td></tr>`).join("")}
        </tbody></table></div></div>` : ""}`;
    el.querySelectorAll("[data-k]").forEach((b) => (b.onclick = () => drill(b.dataset.k)));
  }

  // 一题一张卡：作答后停在本题看对错和解析，← → 翻卡。计时只算作答中的时间，看解析不计时。
  // picked[j] 存作答内容（选项文字或输入的答案），没答是 null。
  function drill(kind) {
    const K = kindOf(kind);
    let qs, start = 0;
    if (BANK_KINDS[kind]) {
      const items = bank.kinds[kind].items;
      start = pos(kind) % items.length;
      qs = Array.from({ length: ROUND }, (_, j) => K.make(items[(start + j) % items.length]));
    } else qs = Array.from({ length: ROUND }, () => K.make());
    const issue = BANK_KINDS[kind] ? `第 ${issueOf(kind, start)} 期 · ` : "";
    const picked = Array(ROUND).fill(null), spent = Array(ROUND).fill(0);
    let i = 0, since = Date.now(), done = false;
    const isRight = (j) => picked[j] !== null && norm(picked[j]) === norm(qs[j].answer);
    const answered = () => picked.filter((p) => p !== null).length;
    const correct = () => qs.filter((_, j) => isRight(j)).length;
    const live = () => (picked[i] === null ? (Date.now() - since) / 1000 : 0);
    const elapsed = () => spent.reduce((a, b) => a + b, 0) + live();

    el.innerHTML = `
      <div class="row mb"><button class="btn sm ghost" id="quit">← 结束</button><span class="spacer"></span>
        <span class="small muted">${issue}${esc(K.name)}</span><span class="clock" id="sclock">00:00</span></div>
      <div class="sd-dots mb" id="sdots"></div>
      <div class="sd-stage" id="sstage"><div class="card sd-card"></div></div>`;
    const stage = el.querySelector("#sstage");
    el.querySelector("#quit").onclick = () => { stop(); home(); };

    function cardHTML(j) {
      const q = qs[j], p = picked[j], last = j === ROUND - 1;
      const ok = isRight(j);
      const foot = p === null
        ? `${q.options ? "按 1–4 选择" : "输入答案后按 Enter"}${j > 0 ? " · 点 ‹ 回上一题" : ""}`
        : `${j > 0 ? "← 上一题 · " : ""}<b>→ ${last ? (answered() === ROUND ? "查看成绩" : "回到未答的题") : "下一题"}</b>（Enter / 空格）`;
      const body = q.options
        ? `<div class="drill-opts">${q.options.map((o, k) => {
            let cls = "";
            if (p !== null) cls = o === q.answer ? "right" : o === p ? "wrong" : "dim";
            return `<button data-o="${k}" class="${cls}" ${p !== null ? "disabled" : ""}><span class="key">${k + 1}</span>${esc(o)}</button>`;
          }).join("")}</div>`
        : `<form class="sd-input" autocomplete="off"><input inputmode="numeric" aria-label="答案" value="${esc(p ?? "")}"
            class="${p === null ? "" : ok ? "right" : "wrong"}" ${p !== null ? "disabled" : ""}>
            ${p === null ? `<button class="btn primary">确定</button>` : ""}</form>`;
      return `
        <button class="sd-nav prev" data-go="-1" ${j === 0 ? "disabled" : ""} aria-label="上一题">‹</button>
        <button class="sd-nav next" data-go="1" ${p === null ? "disabled" : ""} aria-label="下一题">›</button>
        <div class="small muted center num">${j + 1} / ${ROUND} · 答对 ${correct()}</div>
        <div class="drill-q" style="white-space:pre-line">${esc(q.q)}</div>
        ${body}
        ${p === null ? "" : `<div class="sd-fb ${ok ? "ok" : "no"}">
          <span class="verdict ${ok ? "ok" : "no"}">${ok ? "✓ 答对了" : `✗ 答案是 ${esc(q.answer)}`}</span>
          <span class="small muted num">用时 ${spent[j].toFixed(1)} 秒</span>
          ${q.explain ? `<div class="ink2 num">${esc(q.explain)}</div>` : ""}</div>`}
        <p class="small muted center mt">${foot}</p>`;
    }

    function paint(card) {
      card.innerHTML = cardHTML(i);
      card.querySelectorAll("[data-o]").forEach((b) => (b.onclick = () => pick(qs[i].options[+b.dataset.o])));
      card.querySelectorAll("[data-go]").forEach((b) => (b.onclick = () => go(+b.dataset.go)));
      const form = card.querySelector(".sd-input");
      if (form) {
        const input = form.querySelector("input");
        form.onsubmit = (e) => { e.preventDefault(); if (norm(input.value)) pick(input.value.trim()); };
        if (picked[i] === null) requestAnimationFrame(() => input.focus({ preventScroll: true }));
      }
      el.querySelector("#sdots").innerHTML = qs.map((q, j) => {
        const cls = picked[j] === null ? "" : isRight(j) ? "right" : "wrong";
        return `<i class="${cls} ${j === i ? "cur" : ""}" data-j="${j}" title="第 ${j + 1} 题"></i>`;
      }).join("");
      el.querySelectorAll("#sdots [data-j]").forEach((d) => (d.onclick = () => jump(+d.dataset.j)));
    }
    const current = () => stage.querySelector(".sd-card:not(.leaving)");

    function pick(v) {
      if (done || picked[i] !== null || v == null) return;
      spent[i] += (Date.now() - since) / 1000;
      picked[i] = v;
      const card = current();
      paint(card);
      const ok = isRight(i);
      const k = qs[i].options ? qs[i].options.indexOf(v) : -1;
      (card.querySelector(k >= 0 ? `[data-o="${k}"]` : ".sd-input input")).animate(
        ok ? [{ transform: "scale(1)" }, { transform: "scale(1.06)" }, { transform: "scale(1)" }]
           : [{ transform: "translateX(0)" }, { transform: "translateX(-7px)" }, { transform: "translateX(6px)" }, { transform: "translateX(-3px)" }, { transform: "translateX(0)" }],
        { duration: ok ? 260 : 320, easing: "ease-out" });
    }

    // 只能往前翻到第一道没答的题
    const frontier = () => { const f = picked.indexOf(null); return f === -1 ? ROUND - 1 : f; };
    function go(d) {
      if (done) return;
      if (d > 0 && picked[i] === null) return;
      if (d > 0 && i === ROUND - 1) { if (answered() === ROUND) finish(); else jump(frontier()); return; }
      jump(i + d);
    }

    function jump(j) {
      if (done || j === i || j < 0 || j >= ROUND || j > frontier()) return;
      if (picked[i] === null) spent[i] += (Date.now() - since) / 1000;
      const dir = j > i ? 1 : -1;
      i = j; since = Date.now();
      slide(dir);
    }

    function slide(dir) {
      stage.querySelectorAll(".sd-card.leaving").forEach((c) => c.remove());
      const old = current(), fresh = document.createElement("div");
      fresh.className = "card sd-card";
      paint(fresh);
      const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
      if (reduce) { old.replaceWith(fresh); return; }
      old.classList.add("leaving");
      old.style.top = old.offsetTop + "px";
      stage.appendChild(fresh);
      const ease = "cubic-bezier(.22,.8,.24,1)";
      old.animate([
        { transform: "none", opacity: 1 },
        { transform: `translateX(${-dir * 70}%) rotate(${-dir * 4}deg)`, opacity: 0 },
      ], { duration: 340, easing: ease, fill: "forwards" });
      setTimeout(() => old.remove(), 360);
      fresh.animate([
        { transform: `translateX(${dir * 70}%) rotate(${dir * 4}deg)`, opacity: 0 },
        { transform: "none", opacity: 1 },
      ], { duration: 380, easing: ease });
    }

    async function finish() {
      done = true;
      stop();
      const seconds = Math.round(elapsed()), right = correct();
      try { await apiPost("/api/speed", { kind, total: ROUND, correct: right, seconds }); } catch (e) { toast(e.message); }
      if (BANK_KINDS[kind]) store.set("speed_pos", { ...store.get("speed_pos", {}), [kind]: (start + ROUND) % bank.kinds[kind].items.length });
      records = (await apiGet("/api/stats")).speed;
      const wrong = qs.map((q, j) => ({ q, p: picked[j], j })).filter((x) => !isRight(x.j));
      el.innerHTML = `<div class="card empty"><h3>${issue}${esc(K.name)} · 本轮结束</h3>
        <div class="score-big mt">${right}<small> / ${ROUND}</small></div>
        <p>净用时 ${fmtClock(seconds)}，平均每题 ${(seconds / ROUND).toFixed(1)} 秒（看解析的时间不算）</p>
        <div class="row" style="justify-content:center"><button class="btn primary" id="again">再来一轮</button><button class="btn" id="home">换个项目</button></div></div>
        ${wrong.length ? `<div class="card mt"><h3 class="mb">本轮错题</h3><div class="table-wrap"><table class="tbl">
          <thead><tr><th>题目</th><th class="n">你的答案</th><th class="n">答案</th><th>解析</th></tr></thead><tbody>
          ${wrong.map(({ q, p }) => `<tr><td>${esc(q.q.replace(/\n/g, " "))}</td><td class="n" style="color:var(--bad)">${esc(p)}</td>
            <td class="n">${esc(q.answer)}</td><td class="small ink2">${esc(q.explain || "")}</td></tr>`).join("")}
          </tbody></table></div></div>` : ""}`;
      el.querySelector("#again").onclick = () => drill(kind);
      el.querySelector("#home").onclick = home;
    }

    function stop() { clearInterval(tick); if (keyHandler) document.removeEventListener("keydown", keyHandler); keyHandler = null; }
    stop();
    const clock = el.querySelector("#sclock");
    tick = setInterval(() => { clock.textContent = fmtClock(elapsed()); }, 200);
    keyHandler = (e) => {
      if (e.ctrlKey || e.altKey || e.metaKey || /^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)) return;
      const q = qs[i];
      if (/^[0-9-]$/.test(e.key) && !q.options && picked[i] === null) current().querySelector(".sd-input input")?.focus();
      else if (["1", "2", "3", "4"].includes(e.key) && q.options) pick(q.options[+e.key - 1]);
      else if (e.key === "ArrowRight" || e.key === "Enter" || e.key === " ") { e.preventDefault(); go(1); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); go(-1); }
    };
    document.addEventListener("keydown", keyHandler);
    // 触屏左右滑
    let tx = null;
    stage.addEventListener("touchstart", (e) => { tx = e.touches[0].clientX; }, { passive: true });
    stage.addEventListener("touchend", (e) => {
      if (tx === null) return;
      const dx = e.changedTouches[0].clientX - tx; tx = null;
      if (Math.abs(dx) > 50) go(dx < 0 ? 1 : -1);
    });
    paint(current());
  }

  home();
  return () => { clearInterval(tick); if (keyHandler) document.removeEventListener("keydown", keyHandler); };
}
