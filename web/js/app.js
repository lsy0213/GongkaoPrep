// 路由与外壳：根据地址栏 # 后面的路径加载对应页面；侧栏底部是专注计时器。
// 侧栏菜单、路由、计时科目来自当前考试的清单（content/exams/<id>/exam.json），左上角可以切换考试
import { EXAM, apiGet, apiPost, applyLook, esc, fmtClock, initExam, initStore, parseHash, store, switchExam, toast } from "./lib.js";
import { decorateNav, setBottomBadge, syncBottomNav } from "./navx.js";

await initExam();
await initStore();

// 外观：界面风格 + 跟随系统 / 浅色 / 深色（在设置页切换）
applyLook();
buildShell();
// 从哪里打开的（本机 / 局域网手机 / 服务器）：整理资料这类只能在电脑上做的操作，在手机和服务器上不显示
apiGet("/api/session").then((r) => (document.documentElement.dataset.mode = r.mode)).catch(() => {});

// 侧栏收起成图标栏，状态保存在本机
document.body.classList.toggle("nav-collapsed", !!store.get("nav-collapsed", false));
document.getElementById("nav-toggle").onclick = () => {
  const on = !document.body.classList.contains("nav-collapsed");
  document.body.classList.toggle("nav-collapsed", on);
  store.set("nav-collapsed", on);
};

// 侧栏分组可折叠；第一次打开时只展开当前页所在的组，之后记住用户的选择
const navSecs = [...document.querySelectorAll(".nav-sec")];
let folded = store.get("nav-folded", null);
function setFolded(sec, on) {
  sec.classList.toggle("folded", on);
  sec.querySelector(".nav-group").setAttribute("aria-expanded", String(!on));
}
function saveFolded() {
  folded = navSecs.filter((s) => s.classList.contains("folded")).map((s) => s.dataset.sec);
  store.set("nav-folded", folded);
}
navSecs.forEach((sec) => {
  sec.querySelector(".nav-group").onclick = () => { setFolded(sec, !sec.classList.contains("folded")); saveFolded(); };
});
function revealActiveSec() {
  const sec = document.querySelector("#nav a.active")?.closest(".nav-sec");
  if (folded === null) {
    navSecs.forEach((s) => setFolded(s, s !== sec));
    saveFolded();
  } else if (sec?.classList.contains("folded")) {
    setFolded(sec, false);
    saveFolded();
  }
}
navSecs.forEach((s) => setFolded(s, !!folded?.includes(s.dataset.sec)));

// 手机上的抽屉菜单：点菜单按钮打开，点导航项或遮罩关闭
document.getElementById("mobile-menu").onclick = () => document.body.classList.toggle("nav-open");
document.getElementById("nav-scrim").onclick = () => document.body.classList.remove("nav-open");
document.getElementById("nav").addEventListener("click", (e) => { if (e.target.closest("a.nav-item")) document.body.classList.remove("nav-open"); });

// 路由 → 页面模块（pages/ 下的路径）。每门考试自己定，没有的路由回首页
const ROUTES = EXAM.cur.routes || { "": "home" };

// ---------------------------------------------------------------- 侧栏：菜单、考试切换

// 清单里的菜单：{route, label, glyph, badge} 是一项；{sec, label, items} 是可折叠的一组；{sep} 是分隔线
function navItemHTML(it) {
  const badge = it.badge ? `<span class="badge" id="badge-${esc(it.badge)}" hidden></span>` : "";
  return `<a class="nav-item" href="#/${esc(it.route)}" data-route="${esc(it.route)}"><span class="ico">${esc(it.glyph || "·")}</span><span class="label">${esc(it.label)}</span>${badge}</a>`;
}
function navHTML(items) {
  return (items || []).map((it) => {
    if (it.sep) return `<div class="nav-sep"></div>`;
    if (it.sec) {
      return `<div class="nav-sec" data-sec="${esc(it.sec)}">
        <button class="nav-group" type="button" aria-expanded="true"><span class="ico caret" aria-hidden="true">›</span><span class="label">${esc(it.label)}</span></button>
        <div class="nav-sec-body"><div><div>${(it.items || []).map(navItemHTML).join("")}</div></div></div>
      </div>`;
    }
    return navItemHTML(it);
  }).join("");
}

function examEmblem(e, cls = "exs-em") {
  return `<span class="${cls}" style="--exs:${esc(e.color || "#8C6D35")}">${esc(e.emblem || (e.short || e.name || "?").slice(0, 1))}</span>`;
}

function buildShell() {
  const ex = EXAM.cur;
  document.getElementById("nav").innerHTML = navHTML(ex.nav);
  if (ex.brand_sub) document.querySelector(".brand-sub").textContent = ex.brand_sub;
  if (ex.title) document.title = ex.title;
  document.documentElement.dataset.exam = ex.id;
  const box = document.getElementById("exam-switch");
  if (box && EXAM.list.length > 1) {
    box.innerHTML = `
      <button class="exs-btn" id="exs-btn" type="button" aria-haspopup="true" aria-expanded="false" title="切换考试">
        ${examEmblem(ex)}
        <span class="exs-txt"><span class="exs-k">当前考试 ⇄</span><span class="exs-n">${esc(ex.short || ex.name)}</span></span>
        <span class="exs-caret" aria-hidden="true">⌄</span>
      </button>
      <div class="exs-menu" id="exs-menu" hidden>
        <div class="exs-h">切换考试</div>
        ${EXAM.list.map((e) => `<button class="exs-it${e.id === ex.id ? " on" : ""}" type="button" data-ex="${esc(e.id)}">
          ${examEmblem(e)}<span class="exs-t"><b>${esc(e.family || "")}${e.family ? " · " : ""}${esc(e.name)}</b><small>${esc(e.level ? e.level + " · " : "")}${esc(e.desc || "")}</small></span>
          <span class="exs-ck" aria-hidden="true">${e.id === ex.id ? "✓" : "›"}</span></button>`).join("")}
        <div class="exs-sep"></div>
        <a class="exs-it" href="#/exams"><span class="exs-em plain">◫</span><span class="exs-t"><b>全部考试总览</b><small>几门考试的倒计时和进度放一屏</small></span><span class="exs-ck" aria-hidden="true">›</span></a>
      </div>`;
    const btn = box.querySelector("#exs-btn"), menu = box.querySelector("#exs-menu");
    const show = (on) => { menu.hidden = !on; btn.setAttribute("aria-expanded", String(on)); box.classList.toggle("open", on); };
    btn.onclick = (e) => { e.stopPropagation(); show(menu.hidden); };
    menu.onclick = (e) => {
      const it = e.target.closest("[data-ex]");
      if (it) switchExam(it.dataset.ex);
      else if (e.target.closest("a")) show(false);
    };
    document.addEventListener("click", (e) => { if (!box.contains(e.target)) show(false); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") show(false); });
  } else if (box) {
    box.remove();
  }
  decorateNav();
}

const view = document.getElementById("view");
let cleanup = null;
let renderSeq = 0;

async function route() {
  const ctx = parseHash();
  const name = ROUTES[ctx.route] || ROUTES[""] || "home";
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === (ROUTES[ctx.route] ? ctx.route : "")));
  revealActiveSec();
  syncBottomNav(ROUTES[ctx.route] ? ctx.route : "");
  if (typeof cleanup === "function") {
    try { cleanup(); } catch { /* 忽略清理错误 */ }
  }
  cleanup = null;
  const seq = ++renderSeq;
  view.innerHTML = `<div class="empty">翻开这一页…</div>`;
  try {
    const mod = await import(`./pages/${name}.js`);
    if (seq !== renderSeq) return;
    view.scrollTop = 0;
    cleanup = await mod.render(view, ctx);
    pageIn();
    if (seq === renderSeq && name !== "resume") {
      const { draftBannerHTML } = await import("./quiz.js");
      view.insertAdjacentHTML("afterbegin", draftBannerHTML());
    }
  } catch (e) {
    console.error(e);
    view.innerHTML = `<div class="card empty"><h3>页面出错了</h3><p>${esc(e.message)}</p>
      <p class="small">可以按 F5 重新载入；如果仍有问题，请关闭软件后重新打开。</p></div>`;
  }
  refreshBadge();
}

export async function refreshBadge() {
  try {
    const d = await apiGet("/api/wrongbook");
    const due = d.items.filter((x) => !x.mastered && x.next_review <= d.today).length;
    const b = document.getElementById("badge-wrong");
    if (b) { b.textContent = due; b.hidden = !due; }
    setBottomBadge(due);
  } catch { /* 角标失败不影响页面 */ }
}

window.addEventListener("hashchange", route);

// 换页面时新页面轻轻浮上来（只在换页时播一次；同一页里重新渲染不播）
function pageIn() {
  view.classList.remove("page-in");
  void view.offsetWidth;
  view.classList.add("page-in");
}
view.addEventListener("animationend", (e) => { if (e.target === view) view.classList.remove("page-in"); });

// “放弃”没做完的题
document.addEventListener("click", async (e) => {
  const b = e.target.closest?.("[data-draft-drop]");
  if (!b) return;
  if (!b.dataset.armed) { b.dataset.armed = "1"; b.textContent = "确认放弃"; return; }
  const { dropQuizDraft } = await import("./quiz.js");
  dropQuizDraft();
  document.getElementById("draft-bar")?.remove();
  toast("已放弃；做过的题不会记成绩");
});

// ---------------------------------------------------------------- 专注计时器

// 计时的科目由考试清单定（公考：言语、数量……；软考：综合知识、案例分析、论文……）
const TIMER_CFG = EXAM.cur.timer || {};
const TIMER_MODULES = TIMER_CFG.modules || ["综合"];
const TIMER_SHORT = TIMER_CFG.short || {};
const timerEl = document.getElementById("timer");
let timer = store.get("timer", { running: false, minutes: 25, module: TIMER_CFG.default || TIMER_MODULES[0], endAt: 0, startedAt: 0, remaining: 25 * 60 });
if (!TIMER_MODULES.includes(timer.module)) timer.module = TIMER_CFG.default || TIMER_MODULES[0];
let tick = null;

function saveTimer() { store.set("timer", timer); }

function remainingSec() {
  return timer.running ? Math.max(0, (timer.endAt - Date.now()) / 1000) : timer.remaining;
}

function beep() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    [0, 0.35, 0.7].forEach((t) => {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.frequency.value = 880; o.connect(g); g.connect(ctx.destination);
      g.gain.setValueAtTime(0.15, ctx.currentTime + t);
      g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + t + 0.3);
      o.start(ctx.currentTime + t); o.stop(ctx.currentTime + t + 0.32);
    });
  } catch { /* 没有声音也没关系 */ }
}

async function logMinutes(minutes, label) {
  if (minutes < 1) return;
  try {
    await apiPost("/api/study_log", { module: timer.module, minutes, source: "专注计时" });
    toast(`${label}：已记录 ${timer.module} ${minutes} 分钟`);
  } catch (e) { toast(e.message); }
}

function renderTimer() {
  const left = remainingSec();
  const elapsedMin = Math.floor((timer.minutes * 60 - left) / 60);
  timerEl.classList.toggle("running", timer.running);
  timerEl.innerHTML = `
    <div class="row" style="flex-wrap:nowrap"><span class="timer-label">专注</span><span class="spacer"></span>
      <select id="tm-mod" aria-label="学习科目">${TIMER_MODULES.map((m) => `<option value="${m}" ${m === timer.module ? "selected" : ""}>${TIMER_SHORT[m] || m}</option>`).join("")}</select>
      <select id="tm-len" aria-label="时长" ${timer.running ? "disabled" : ""}>${[25, 45, 60, 90].map((m) => `<option value="${m}" ${m === timer.minutes ? "selected" : ""}>${m} 分</option>`).join("")}</select></div>
    <div class="row" style="margin-top:4px">
      <span class="tm" id="tm-clock">${fmtClock(left)}</span><span class="spacer"></span>
      <button class="btn sm primary" id="tm-go">${timer.running ? "暂停" : left < timer.minutes * 60 ? "继续" : "开始"}</button>
      ${left < timer.minutes * 60 ? `<button class="btn sm" id="tm-end" title="结束并记录已学习的时间">${elapsedMin >= 1 ? "记录" : "结束"}</button>` : ""}
    </div>`;
  timerEl.querySelector("#tm-mod").onchange = (e) => { timer.module = e.target.value; saveTimer(); };
  timerEl.querySelector("#tm-len").onchange = (e) => {
    timer.minutes = +e.target.value; timer.remaining = timer.minutes * 60; saveTimer(); renderTimer();
  };
  timerEl.querySelector("#tm-go").onclick = () => {
    if (timer.running) {
      timer.remaining = remainingSec(); timer.running = false;
      document.title = "上岸备考";
    } else {
      timer.running = true; timer.endAt = Date.now() + timer.remaining * 1000;
    }
    saveTimer(); renderTimer(); startTick();
  };
  const end = timerEl.querySelector("#tm-end");
  if (end) end.onclick = async () => {
    const minutes = Math.floor((timer.minutes * 60 - remainingSec()) / 60);
    timer.running = false; timer.remaining = timer.minutes * 60; saveTimer(); renderTimer();
    clearInterval(tick);
    document.title = "上岸备考";
    await logMinutes(minutes, "已结束");
  };
}

function startTick() {
  clearInterval(tick);
  if (!timer.running) return;
  tick = setInterval(async () => {
    const left = remainingSec();
    const c = document.getElementById("tm-clock");
    if (c) c.textContent = fmtClock(left);
    document.title = `${fmtClock(left)} · 上岸备考`;
    if (left <= 0) {
      clearInterval(tick);
      document.title = "上岸备考";
      const minutes = timer.minutes;
      timer.running = false; timer.remaining = timer.minutes * 60; saveTimer(); renderTimer();
      beep();
      await logMinutes(minutes, "专注完成");
    }
  }, 500);
}

renderTimer();
startTick();
route();
