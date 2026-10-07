// 路由与外壳：根据地址栏 # 后面的路径加载对应页面；侧栏底部是专注计时器
import { apiGet, apiPost, esc, fmtClock, initStore, parseHash, store, toast } from "./lib.js";

await initStore();

// 外观：跟随系统 / 浅色 / 深色（在设置页切换）
const savedTheme = store.get("theme", "system");
if (savedTheme !== "system") document.documentElement.setAttribute("data-theme", savedTheme);

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

const ROUTES = {
  "": "home", plan: "plan", learn: "learn", notes: "notes", cards: "cards", practice: "practice",
  mock: "mock", speed: "speed", essay: "essay", interview: "interview", wrong: "wrong", memo: "memo", real: "real", library: "library", news: "news",
  stats: "stats", ai: "ai", settings: "settings", resume: "resume", positions: "positions",
};

const view = document.getElementById("view");
let cleanup = null;
let renderSeq = 0;

async function route() {
  const ctx = parseHash();
  const name = ROUTES[ctx.route] || "home";
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === (ROUTES[ctx.route] ? ctx.route : "")));
  revealActiveSec();
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
    b.textContent = due;
    b.hidden = !due;
  } catch { /* 角标失败不影响页面 */ }
}

window.addEventListener("hashchange", route);

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

const TIMER_MODULES = ["言语理解与表达", "数量关系", "判断推理", "资料分析", "政治理论", "常识判断", "申论", "面试", "阅读积累", "综合"];
const TIMER_SHORT = { "言语理解与表达": "言语", "数量关系": "数量", "判断推理": "判断", "资料分析": "资料", "政治理论": "政治", "常识判断": "常识", "阅读积累": "积累" };
const timerEl = document.getElementById("timer");
let timer = store.get("timer", { running: false, minutes: 25, module: "综合", endAt: 0, startedAt: 0, remaining: 25 * 60 });
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
