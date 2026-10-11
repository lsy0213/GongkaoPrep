// 软考计算题生成器：每类题由程序出题、程序算答案和解题步骤，干扰项按常见错误生成。
// 每个生成器返回 { stem, table?, options: [4 个字符串], answer: 0–3, steps: [文字] }
const R = (a, b) => a + Math.floor(Math.random() * (b - a + 1));
const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];
const shuffle = (a) => { for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };
const fmt = (x, d = 4) => String(+x.toFixed(d));

// 正确答案 + 干扰项 → 四个不重复的选项（干扰项不够时按正确答案上下浮动补）
function choices(right, wrongs, toStr = String, nudge = null) {
  const seen = new Set([toStr(right)]);
  const opts = [right];
  for (const w of wrongs) {
    if (opts.length >= 4) break;
    const s = toStr(w);
    if (w == null || Number.isNaN(w) || seen.has(s)) continue;
    seen.add(s); opts.push(w);
  }
  for (let k = 1; opts.length < 4 && k < 50; k++) {
    const w = nudge ? nudge(right, k) : right + (k % 2 ? k : -k);
    const s = toStr(w);
    if (seen.has(s) || (typeof w === "number" && w < 0)) continue;
    seen.add(s); opts.push(w);
  }
  const order = shuffle(opts.map((v, i) => ({ v, i })));
  return { options: order.map((o) => toStr(o.v)), answer: order.findIndex((o) => o.i === 0) };
}

// ---------------------------------------------------------------- 1. 关键路径
function cpm() {
  const names = "ABCDEFGH".slice(0, R(6, 8)).split("");
  const acts = names.map((n, i) => {
    const pre = i === 0 ? [] : shuffle(names.slice(0, i)).slice(0, i < 2 ? 1 : R(1, Math.min(2, i)));
    return { n, d: R(2, 9), pre: pre.sort() };
  });
  const es = {}, ef = {};
  for (const a of acts) { es[a.n] = Math.max(0, ...a.pre.map((p) => ef[p])); ef[a.n] = es[a.n] + a.d; }
  const T = Math.max(...Object.values(ef));
  const lf = {}, ls = {};
  for (const a of [...acts].reverse()) {
    const succ = acts.filter((x) => x.pre.includes(a.n));
    lf[a.n] = succ.length ? Math.min(...succ.map((s) => ls[s.n])) : T;
    ls[a.n] = lf[a.n] - a.d;
  }
  const crit = acts.filter((a) => ls[a.n] === es[a.n]).map((a) => a.n);
  const askSlack = Math.random() < 0.45 && acts.some((a) => ls[a.n] > es[a.n]);
  const table = [["活动", "紧前活动", "工期（天）"], ...acts.map((a) => [a.n, a.pre.join("、") || "—", String(a.d)])];
  const steps = [
    `正推求最早开始 / 最早完成（ES / EF）：${acts.map((a) => `${a.n} ${es[a.n]}/${ef[a.n]}`).join("，")}。`,
    `总工期 = 最大的 EF = ${T} 天。`,
    `逆推求最迟完成 / 最迟开始（LF / LS）：${acts.map((a) => `${a.n} ${lf[a.n]}/${ls[a.n]}`).join("，")}。`,
    `总时差 = LS − ES，为 0 的活动在关键路径上：${crit.join("、")}。`,
  ];
  if (askSlack) {
    const a = pick(acts.filter((x) => ls[x.n] > es[x.n]));
    const slack = ls[a.n] - es[a.n];
    return { stem: `某项目的活动如下表所示。活动 ${a.n} 的总时差为（ ）天。`, table, steps,
      ...choices(slack, [0, a.d, lf[a.n] - ef[a.n] + 1, T - ef[a.n]]) };
  }
  const sum = acts.reduce((x, a) => x + a.d, 0);
  return { stem: "某项目的活动如下表所示，该项目的总工期为（ ）天。", table, steps,
    ...choices(T, [sum, T - Math.min(...acts.map((a) => a.d)), T + R(1, 3), Math.max(...acts.map((a) => a.d)) * 2]) };
}

// ---------------------------------------------------------------- 2. 系统可靠度
function reliability() {
  const r = () => pick([0.8, 0.85, 0.9, 0.95, 0.98, 0.99]);
  const kind = R(0, 2);
  if (kind === 0) { // 两个并联再串一个
    const a = r(), b = r(), c = r();
    const par = 1 - (1 - a) * (1 - b), ans = par * c;
    return { stem: `部件 R1、R2 的可靠度分别为 ${a}、${b}，二者并联后再与可靠度为 ${c} 的 R3 串联，系统的可靠度为（ ）。`,
      steps: [`并联：1 − (1 − ${a}) × (1 − ${b}) = ${fmt(par)}`, `再串联：${fmt(par)} × ${c} = ${fmt(ans)}`],
      ...choices(ans, [a * b * c, par, 1 - (1 - a * b) * (1 - c), (a + b) / 2 * c], (x) => fmt(x)) };
  }
  if (kind === 1) { // n 个相同部件串联 / 并联
    const p = r(), n = R(2, 4), ser = Math.random() < 0.5;
    const ans = ser ? p ** n : 1 - (1 - p) ** n;
    return { stem: `由 ${n} 个可靠度都是 ${p} 的部件${ser ? "串联" : "并联"}组成的系统，可靠度为（ ）。`,
      steps: [ser ? `串联：R = R1 × R2 × … = ${p}^${n} = ${fmt(ans)}` : `并联：R = 1 − (1 − ${p})^${n} = ${fmt(ans)}`],
      ...choices(ans, [ser ? 1 - (1 - p) ** n : p ** n, p, p * n > 1 ? 1 - p : p * n], (x) => fmt(x)) };
  }
  // 两个串联的支路再并联
  const a = r(), b = r(), c = r(), d = r();
  const s1 = a * b, s2 = c * d, ans = 1 - (1 - s1) * (1 - s2);
  return { stem: `系统由两条支路并联组成：支路一是可靠度 ${a}、${b} 的两个部件串联，支路二是可靠度 ${c}、${d} 的两个部件串联。系统可靠度为（ ）。`,
    steps: [`支路一：${a} × ${b} = ${fmt(s1)}；支路二：${c} × ${d} = ${fmt(s2)}`, `两支路并联：1 − (1 − ${fmt(s1)}) × (1 − ${fmt(s2)}) = ${fmt(ans)}`],
    ...choices(ans, [s1 * s2, (1 - (1 - a) * (1 - c)) * (1 - (1 - b) * (1 - d)), s1 + s2 - 1 > 0 ? s1 + s2 - 1 : 0.5], (x) => fmt(x)) };
}

// ---------------------------------------------------------------- 3. 信号量
function semaphore() {
  const m = R(1, 4), n = R(m + 2, m + 7);
  if (Math.random() < 0.5) {
    const rng = (lo) => `${m}～−${n - lo}`;
    return { stem: `有 ${n} 个进程共享 ${m} 台打印机（每个进程最多用 1 台），用 PV 操作控制，信号量 S 的取值范围是（ ）。`,
      steps: [`初值 = 资源数 = ${m}；最坏情况下 ${n} 个进程都申请，S 最小为 ${m} − ${n} = ${m - n}。`, `所以 S 的范围是 ${m}～${m - n}。`],
      ...choices(rng(m), [`${n}～−${m}`, `1～−${n - 1}`, `${m}～0`, `0～−${n}`]) };
  }
  const k = R(1, n - m);
  return { stem: `有 ${n} 个进程共享 ${m} 台打印机，用 PV 操作控制。若某时刻信号量 S = −${k}，则有（ ）个进程在等待打印机。`,
    steps: [`S < 0 时，|S| 就是等待队列里的进程数：${k} 个。`],
    ...choices(k, [k + m, m, n - k, k - 1]) };
}

// ---------------------------------------------------------------- 4. 页式地址变换
function paging() {
  const kb = pick([1, 2, 4]), size = kb * 1024;
  const frames = shuffle([2, 3, 5, 6, 7, 8, 9, 11]).slice(0, 4);
  const page = R(0, 3), off = R(1, size - 1), logical = page * size + off;
  const phys = frames[page] * size + off;
  const hex = Math.random() < 0.5;
  const f = (v) => (hex ? "0x" + v.toString(16).toUpperCase() : String(v));
  return { stem: `页式存储管理中，页面大小为 ${kb}KB，页表中页号 0～3 对应的物理块号依次为 ${frames.join("、")}。逻辑地址 ${f(logical)} 对应的物理地址是（ ）。`,
    steps: [`页号 = ${logical} ÷ ${size} = ${page}，页内偏移 = ${off}${hex ? `（${f(off)}）` : ""}`,
      `查页表：页号 ${page} → 物理块 ${frames[page]}`, `物理地址 = ${frames[page]} × ${size} + ${off} = ${phys}${hex ? `（${f(phys)}）` : ""}`],
    ...choices(phys, [frames[page] + off, frames[(page + 1) % 4] * size + off, page * size + frames[page], frames[page] * size], f, (x, k) => x + k * size) };
}

// ---------------------------------------------------------------- 5. Cache 平均访问时间
function cache() {
  const h = pick([0.9, 0.92, 0.95, 0.96, 0.98, 0.99]), tc = pick([1, 2, 5, 10]), tm = pick([50, 60, 80, 100, 120, 200]);
  const ans = h * tc + (1 - h) * tm;
  return { stem: `Cache 的命中率为 ${h}，Cache 存取周期 ${tc}ns，主存存取周期 ${tm}ns（未命中时直接访问主存，按 h·Tc +（1 − h）·Tm 计算）。系统的平均访问时间是（ ）ns。`,
    steps: [`T = ${h} × ${tc} + (1 − ${h}) × ${tm} = ${fmt(h * tc)} + ${fmt((1 - h) * tm)} = ${fmt(ans)} ns`],
    ...choices(ans, [h * tc + (1 - h) * (tc + tm), (tc + tm) / 2, h * tm + (1 - h) * tc, tc + (1 - h) * tm + 1], (x) => fmt(x, 2), (x, k) => x + k * 0.5) };
}

// ---------------------------------------------------------------- 6. 流水线
function pipeline() {
  const st = Array.from({ length: R(3, 5) }, () => R(1, 4));
  const n = pick([10, 20, 50, 100]);
  const sum = st.reduce((a, x) => a + x, 0), mx = Math.max(...st);
  const T = sum + (n - 1) * mx;
  if (Math.random() < 0.6) {
    return { stem: `某指令流水线分 ${st.length} 段，各段时间依次为 ${st.join("Δt、")}Δt。连续执行 ${n} 条指令需要（ ）Δt。`,
      steps: [`第一条指令走完全部段：${st.join(" + ")} = ${sum}Δt`, `之后每 ${mx}Δt（最慢一段）完成一条：(${n} − 1) × ${mx} = ${(n - 1) * mx}Δt`, `合计 ${T}Δt`],
      ...choices(T, [sum * n, n * mx, sum + n * mx, (n - 1) * sum + mx]) };
  }
  const tp = n / T;
  return { stem: `某指令流水线分 ${st.length} 段，各段时间依次为 ${st.join("Δt、")}Δt。连续执行 ${n} 条指令时，流水线的实际吞吐率为（ ）（单位：条/Δt）。`,
    steps: [`总时间 = ${sum} + (${n} − 1) × ${mx} = ${T}Δt`, `吞吐率 = 指令数 ÷ 总时间 = ${n} / ${T} ≈ ${fmt(tp)}`],
    ...choices(tp, [1 / mx, n / (sum * n), 1 / sum, n / (sum + n * mx)], (x) => fmt(x), (x, k) => x * (1 + 0.07 * k)) };
}

// ---------------------------------------------------------------- 7. 磁盘调度
function disk() {
  const head = R(40, 120);
  const reqs = shuffle(Array.from(new Set(Array.from({ length: 7 }, () => R(5, 190))))).slice(0, 6);
  const algo = pick(["FCFS", "SSTF"]);
  let pos = head, total = 0, order = [];
  if (algo === "FCFS") order = reqs.slice();
  else {
    const left = reqs.slice();
    while (left.length) {
      left.sort((a, b) => Math.abs(a - pos) - Math.abs(b - pos) || a - b);
      order.push(left.shift()); pos = order[order.length - 1];
    }
    pos = head;
  }
  for (const r of order) { total += Math.abs(r - pos); pos = r; }
  let fcfs = 0; pos = head; for (const r of reqs) { fcfs += Math.abs(r - pos); pos = r; }
  const sorted = [...reqs].sort((a, b) => a - b);
  const scanUp = (Math.max(...reqs) - head) + (Math.max(...reqs) - Math.min(...reqs));
  return { stem: `磁头当前在 ${head} 号柱面，请求队列（按到达顺序）为 ${reqs.join("、")}。采用 ${algo === "FCFS" ? "先来先服务（FCFS）" : "最短寻道时间优先（SSTF）"}算法，磁头移动的总柱面数为（ ）。`,
    steps: [`访问顺序：${head} → ${order.join(" → ")}`, `移动距离：${order.map((r, i) => Math.abs(r - (i ? order[i - 1] : head))).join(" + ")} = ${total}`],
    ...choices(total, [algo === "FCFS" ? scanUp : fcfs, sorted[sorted.length - 1] - sorted[0], total + head % 10 + 7, scanUp + 10]) };
}

// ---------------------------------------------------------------- 8. 候选键
function closure(attrs, fds) {
  const c = new Set(attrs);
  let changed = true;
  while (changed) {
    changed = false;
    for (const [l, r] of fds) if ([...l].every((x) => c.has(x)) && [...r].some((x) => !c.has(x))) { [...r].forEach((x) => c.add(x)); changed = true; }
  }
  return c;
}
function candKey() {
  for (let tries = 0; tries < 200; tries++) {
    const U = "ABCDE".slice(0, R(4, 5)).split("");
    const fds = [];
    for (let i = 0; i < R(3, 4); i++) {
      const l = shuffle(U.slice()).slice(0, R(1, 2)).sort().join("");
      const r = pick(U.filter((x) => !l.includes(x)));
      if (!fds.some(([a, b]) => a === l && b === r)) fds.push([l, r]);
    }
    const subsets = [];
    for (let m = 1; m < 1 << U.length; m++) subsets.push(U.filter((_, i) => m & (1 << i)).join(""));
    const keys = subsets.filter((s) => closure(s, fds).size === U.length && ![...s].some((x) => closure(s.replace(x, ""), fds).size === U.length));
    if (keys.length !== 1) continue;
    const key = keys[0];
    const wrong = subsets.filter((s) => s !== key && s.length <= key.length + 1 && closure(s, fds).size < U.length);
    const sup = subsets.find((s) => s.length === key.length + 1 && [...key].every((x) => s.includes(x)));
    const w = shuffle(wrong).slice(0, 2);
    if (sup) w.push(sup);
    return { stem: `关系模式 R(${U.join(", ")})，函数依赖集 F = { ${fds.map(([l, r]) => `${l}→${r}`).join("，")} }。R 的候选键为（ ）。`,
      steps: [`只出现在左边（或两边都不出现）的属性一定在键里：${U.filter((x) => !fds.some(([, r]) => r.includes(x))).join("") || "无"}`,
        `${key} 的闭包 = ${[...closure(key, fds)].sort().join("")}，包含全部属性；去掉任何一个属性都不行，所以是候选键（唯一的）。`,
        ...(sup ? [`${sup} 虽然也能推出全部属性，但不是最小的（是超键）。`] : [])],
      ...choices(key, w) };
  }
  return reliability();
}

// ---------------------------------------------------------------- 9. 子网划分
function subnet() {
  const n = pick([2, 4, 8, 16, 32]), bits = Math.log2(n), hostBits = 8 - bits;
  const ip = `192.168.${R(1, 254)}.0`;
  const mask = 256 - 2 ** hostBits;
  if (Math.random() < 0.5) {
    const hosts = 2 ** hostBits - 2;
    return { stem: `把网络 ${ip}/24 平均划分成 ${n} 个子网，每个子网最多能容纳（ ）台主机。`,
      steps: [`${n} 个子网要借 ${bits} 位，主机位剩 8 − ${bits} = ${hostBits} 位`, `可用主机数 = 2^${hostBits} − 2 = ${hosts}（去掉网络地址和广播地址）`],
      ...choices(hosts, [2 ** hostBits, 256 / n - 1, hosts - 2, 254 / n | 0]) };
  }
  return { stem: `把网络 ${ip}/24 平均划分成 ${n} 个子网，子网掩码应为（ ）。`,
    steps: [`借 ${bits} 位做子网号，前缀变为 /${24 + bits}`, `最后一个字节：${"1".repeat(bits)}${"0".repeat(hostBits)}（二进制）= ${mask}`, `掩码 255.255.255.${mask}`],
    ...choices(`255.255.255.${mask}`, [`255.255.255.${256 - n}`, `255.255.255.${mask === 128 ? 192 : mask - (256 - mask)}`, `255.255.${mask}.0`, `255.255.255.${(mask + 255) >> 1}`]) };
}

// ---------------------------------------------------------------- 10. 海明码
function hamming() {
  const k = pick([4, 7, 8, 11, 16, 26, 32, 57, 64]);
  let r = 1;
  while (2 ** r < k + r + 1) r++;
  return { stem: `用海明码对 ${k} 位数据进行检错和纠错（纠正 1 位错），至少需要（ ）位校验位。`,
    steps: [`要满足 2^r ≥ k + r + 1：k = ${k}`, `r = ${r - 1} 时 2^${r - 1} = ${2 ** (r - 1)} < ${k + r}；r = ${r} 时 2^${r} = ${2 ** r} ≥ ${k + r + 1}`, `所以至少 ${r} 位`],
    ...choices(r, [r - 1, r + 1, Math.ceil(Math.log2(k)), r + 2]) };
}

// ---------------------------------------------------------------- 11. 期望值决策
function expected() {
  const p = pick([[0.3, 0.5, 0.2], [0.2, 0.5, 0.3], [0.4, 0.4, 0.2], [0.25, 0.5, 0.25]]);
  const plans = ["甲", "乙", "丙"].map((n) => ({ n, v: [R(-20, 60), R(10, 60), R(20, 90)].map((x) => x * 10) }));
  const ev = plans.map((x) => x.v.reduce((a, v, i) => a + v * p[i], 0));
  const best = ev.indexOf(Math.max(...ev));
  if (ev.filter((x) => x === ev[best]).length > 1) return expected();
  const table = [["方案", `滞销（概率 ${p[0]}）`, `一般（概率 ${p[1]}）`, `畅销（概率 ${p[2]}）`],
    ...plans.map((x) => [`方案${x.n}`, ...x.v.map(String)])];
  return { stem: "某公司有三个投资方案，各种市场情况下的收益（万元）和概率如下表。按期望值决策，应选择（ ）。", table,
    steps: plans.map((x, i) => `方案${x.n}：${x.v.map((v, j) => `${v}×${p[j]}`).join(" + ")} = ${fmt(ev[i], 2)}`).concat([`期望收益最大的是方案${plans[best].n}`]),
    ...choices(`方案${plans[best].n}`, plans.filter((_, i) => i !== best).map((x) => `方案${x.n}`).concat(["三个方案一样"])) };
}

// ---------------------------------------------------------------- 12. 不确定型决策准则
function criteria() {
  const plans = ["Ⅰ", "Ⅱ", "Ⅲ"].map((n) => ({ n, v: [R(-5, 15), R(5, 25), R(10, 40)].map((x) => x * 10) }));
  const rule = pick(["乐观", "悲观", "后悔值"]);
  let score, explain;
  if (rule === "乐观") { score = plans.map((x) => Math.max(...x.v)); explain = "乐观（大中取大）：每个方案取最大收益"; }
  else if (rule === "悲观") { score = plans.map((x) => Math.min(...x.v)); explain = "悲观（小中取大）：每个方案取最小收益"; }
  else {
    const colMax = [0, 1, 2].map((j) => Math.max(...plans.map((x) => x.v[j])));
    score = plans.map((x) => -Math.max(...x.v.map((v, j) => colMax[j] - v)));
    explain = `后悔值（大中取小）：每种情况下的最大收益是 ${colMax.join("、")}，后悔值 = 最大收益 − 本方案收益，每个方案取最大后悔值`;
  }
  const best = score.indexOf(Math.max(...score));
  if (score.filter((x) => x === score[best]).length > 1) return criteria();
  return { stem: `某企业有三种方案，在三种市场情况下的收益（万元）如下表。按${rule}准则，应选择（ ）。`,
    table: [["方案", "需求低", "需求中", "需求高"], ...plans.map((x) => [`方案${x.n}`, ...x.v.map(String)])],
    steps: [explain, plans.map((x, i) => `方案${x.n}：${rule === "后悔值" ? "最大后悔值 " + -score[i] : score[i]}`).join("；"),
      `${rule === "后悔值" ? "取最大后悔值最小的" : "取其中最大的"}：方案${plans[best].n}`],
    ...choices(`方案${plans[best].n}`, plans.filter((_, i) => i !== best).map((x) => `方案${x.n}`).concat(["无法确定"])) };
}

export const CALC_TYPES = [
  { id: "cpm", name: "关键路径", gen: cpm, course: "rk-pm" },
  { id: "rel", name: "系统可靠度", gen: reliability, course: "rk-arch" },
  { id: "pv", name: "信号量 PV", gen: semaphore, course: "rk-hw" },
  { id: "page", name: "页式地址", gen: paging, course: "rk-hw" },
  { id: "cache", name: "Cache 访问时间", gen: cache, course: "rk-hw" },
  { id: "pipe", name: "流水线", gen: pipeline, course: "rk-hw" },
  { id: "disk", name: "磁盘调度", gen: disk, course: "rk-hw" },
  { id: "key", name: "候选键", gen: candKey, course: "rk-db" },
  { id: "subnet", name: "子网划分", gen: subnet, course: "rk-hw" },
  { id: "hamming", name: "海明码", gen: hamming, course: "rk-hw" },
  { id: "ev", name: "期望值决策", gen: expected, course: "rk-pm" },
  { id: "crit", name: "决策准则", gen: criteria, course: "rk-pm" },
];
