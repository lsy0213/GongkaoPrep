// 系统教程：学习路径 → 课程 → 课。课文在 content/course/<课 id>.md，互动块由 course.js 渲染
import { apiGet, apiPost, content, esc, mountAIBox, store, toast } from "../lib.js";
import { bindParts, parseLesson, renderParts, scoreOf } from "../course.js";
import { bindHeadSearch, headSearchBox, hlRegex } from "../headsearch.js";
import { mountMindMap } from "../mindmap.js";

const PRACTICE_LINK = {
  "政治理论": "#/practice?module=" + encodeURIComponent("政治理论"),
  "常识判断": "#/practice?module=" + encodeURIComponent("常识判断"),
  "言语理解与表达": "#/practice?module=" + encodeURIComponent("言语理解与表达"),
  "数量关系": "#/practice?module=" + encodeURIComponent("数量关系"),
  "判断推理": "#/practice?module=" + encodeURIComponent("判断推理"),
  "资料分析": "#/practice?module=" + encodeURIComponent("资料分析"),
  "申论": "#/essay",
  "面试": "#/interview",
  "综合": "#/mock",
};

// 学习进度：{ done: {课: 日期}, last: 课, lessons: {课: {quiz, check, drafts, note}} }
function progress() {
  const p = store.get("course", null) || {};
  p.done = p.done || {};
  p.lessons = p.lessons || {};
  return p;
}
function saveProgress(p) { store.set("course", p); }

function flat(index) {
  const out = [];
  index.courses.forEach((c) => c.lessons.forEach((l, i) => out.push({ ...l, course: c, no: i + 1 })));
  return out;
}

export async function render(el, ctx) {
  const index = await content("course/index.json");
  const all = flat(index);
  let id = ctx.parts[1];
  if (id && index.legacy[id]) id = index.legacy[id];
  if (!id) return home(el, index, all);
  if (id === "map") return mapPage(el, index, all, ctx.parts[2]);
  const course = index.courses.find((c) => c.id === id);
  if (course) return coursePage(el, index, course);
  const lesson = all.find((l) => l.id === id);
  if (lesson) return lessonPage(el, index, all, lesson);
  el.innerHTML = `<div class="card empty"><h3>没有找到这一课</h3><a href="#/learn">返回教程</a></div>`;
}

function courseStat(c, p) {
  const done = c.lessons.filter((l) => p.done[l.id]).length;
  const min = c.lessons.reduce((a, l) => a + l.min, 0);
  return { done, total: c.lessons.length, pct: Math.round((done / c.lessons.length) * 100), min };
}

function nextLesson(all, p) {
  if (p.last) {
    const i = all.findIndex((l) => l.id === p.last);
    if (i >= 0 && !p.done[p.last]) return all[i];
    const after = all.slice(i + 1).find((l) => !p.done[l.id]);
    if (after) return after;
  }
  return all.find((l) => !p.done[l.id]);
}

// ---------------------------------------------------------------- 教程首页

function home(el, index, all) {
  const p = progress();
  const doneN = all.filter((l) => p.done[l.id]).length;
  const nxt = nextLesson(all, p);
  const totalMin = all.reduce((a, l) => a + l.min, 0);
  const pct = Math.round((doneN / all.length) * 100);
  el.innerHTML = `
    <div class="page-head"><div><div class="eyebrow">系统教程</div><h1>从零到上岸，一课一课学</h1>
      <p>${index.courses.length} 门课、${all.length} 节互动课，约 ${Math.round(totalMin / 60)} 小时。每节课边学边练：随堂测验、分步例题、填空排序、速算小练、动笔写、开口练，学完马上做对应的真题。</p></div>
      ${headSearchBox("搜索教程", "在教程里搜索")}</div>
    <div class="card continue-card">
      <div class="ct-main">
        ${nxt ? `<div class="eyebrow">${doneN ? "继续学习" : "从这里开始"}</div>
          <div class="small ink2">${esc(nxt.course.title)} · 第 ${nxt.no} 课 · 约 ${nxt.min} 分钟</div>
          <h2>${esc(nxt.title)}</h2>`
        : `<div class="eyebrow">学完了</div><h2>全部 ${all.length} 课都学完了！</h2>
          <div class="small ink2">接下来以真题和模考为主，遇到薄弱点再回来翻对应的课。</div>`}
        <div class="ct-prog"><div class="progress"><i style="width:${pct}%"></i></div>
          <span class="small muted">已学 <span class="num">${doneN} / ${all.length}</span> 课</span></div>
      </div>
      <div class="row ct-act">
        ${nxt ? `<a class="btn ghost" href="#/learn/${nxt.course.id}">本门课目录</a>
          <a class="btn primary lg" href="#/learn/${nxt.id}">${doneN ? "继续学习" : "开始第一课"}</a>`
        : `<a class="btn primary lg" href="#/mock">去模考</a>`}
      </div>
    </div>
    <div class="card row lmap-entry"><div><b>知识导图</b>
      <div class="small ink2">先看全局：笔试、面试各考什么、知识点怎么串起来；再按模块逐门展开，点节点上的 → 直接进入对应的课。</div></div>
      <span class="spacer"></span>
      <div class="lmap-tabs" style="margin:0"><a class="on" href="#/learn/map">总导图</a>${index.courses.map((c) =>
        `<a href="#/learn/map/${c.id}">${esc(c.title)}</a>`).join("")}</div>
    </div>
    ${index.stages.map((s) => {
      const cs = index.courses.filter((c) => c.stage === s.id);
      if (!cs.length) return "";
      return `<div class="stage-head"><span class="stage-no">${s.id}</span><div><h2>${esc(s.name)}</h2>
          <span class="small ink2">${esc(s.desc)} · 建议用时 ${esc(s.time)}</span></div></div>
        <div class="course-grid">${cs.map((c) => {
          const st = courseStat(c, p);
          return `<a class="course-card" href="#/learn/${c.id}">
            <span class="cc-ico">${esc(c.icon)}</span>
            <span class="cc-body"><b>${esc(c.title)}</b><span class="small ink2">${esc(c.desc)}</span>
              <span class="cc-meta small muted">${st.total} 课 · 约 ${Math.round(st.min / 6) / 10} 小时${st.done ? ` · 已学 ${st.done}` : ""}</span>
              <span class="progress"><i style="width:${st.pct}%"></i></span></span></a>`;
        }).join("")}</div>`;
    }).join("")}`;
  return headSearch(el, all);
}

// 页头右上角的小搜索框：搜课文，结果浮在框下方
const HOT = ["截位直除", "增长率", "翻译推理", "图形推理", "逻辑填空", "倡议书", "结构化面试"];

function headSearch(el, all) {
  const byId = Object.fromEntries(all.map((l) => [l.id, l]));
  return bindHeadSearch(el, {
    hot: HOT,
    run: async (q) => {
      const r = await apiGet("/api/course/search?q=" + encodeURIComponent(q));
      const hits = r.hits.filter((h) => byId[h.id]);
      const re = hlRegex(q);
      return hits.length
        ? `<div class="hs-label">${hits.length} 节课提到“${esc(q)}”</div>
          <div class="hs-list">${hits.slice(0, 12).map((h) => {
            const l = byId[h.id];
            return `<a class="hs-hit" data-go href="#/learn/${l.id}"><span class="hs-meta">${esc(l.course.title)} · 第 ${l.no} 课</span>
              <b>${esc(l.title)}</b><span class="snip">${esc(h.snippet).replace(re, (m) => `<mark>${m}</mark>`)}</span></a>`;
          }).join("")}</div>`
        : `<div class="hs-empty">没有找到“${esc(q)}”<br><span class="small muted">换个说法试试，比如题型名或方法名</span></div>`;
    },
  });
}

// ---------------------------------------------------------------- 课程页

function coursePage(el, index, course) {
  const p = progress();
  const st = courseStat(course, p);
  const stage = index.stages.find((s) => s.id === course.stage);
  const first = course.lessons.find((l) => !p.done[l.id]) || course.lessons[0];
  el.innerHTML = `
    <div class="row mb"><a class="btn sm ghost" href="#/learn">← 全部课程</a></div>
    <div class="page-head"><div><div class="eyebrow">第 ${course.stage} 阶段 · ${esc(stage?.name || "")}</div>
      <h1>${esc(course.icon)} ${esc(course.title)}</h1><p>${esc(course.desc)}</p></div>
      <div class="row"><span class="chip brand">已学 ${st.done} / ${st.total}</span>
        <a class="btn primary" href="#/learn/${first.id}">${st.done ? "继续学习" : "开始学习"}</a></div></div>
    <div class="card">
      ${course.lessons.map((l, i) => {
        const sc = scoreOf(p.lessons[l.id]);
        return `<a class="lesson" href="#/learn/${l.id}">
          <span class="idx">${i + 1}</span>
          <span class="body"><b>${esc(l.title)}</b><div>${sc.n ? `随堂练习 ${sc.ok}/${sc.n} 正确` : "&nbsp;"}</div></span>
          <span class="row">${p.done[l.id] ? `<span class="chip good">已学</span>` : ""}<span class="small muted">${l.min} 分钟</span></span></a>`;
      }).join("")}
    </div>
    <div class="card"><div class="card-head"><h3>知识导图</h3><a class="small" href="#/learn/map/${course.id}">大图查看 →</a></div>
      <div class="lmap" id="cmap"></div></div>
    ${PRACTICE_LINK[course.module] ? `<div class="card row"><span class="ink2">学完一课就做对应的题，比全部学完再练效果好得多。</span><span class="spacer"></span>
      <a class="btn" href="${PRACTICE_LINK[course.module]}">去练${esc(course.module === "综合" ? "模考" : course.module)}</a></div>` : ""}`;
  return showMap(el.querySelector("#cmap"), index, flat(index), course.id, { open: 2 });
}

// ---------------------------------------------------------------- 知识导图
// 导图写在 content/course/maps/<课程 id>.txt（总导图是 all.txt）：“# 标题”一行，下面“- 节点”每级缩进两格，
// 节点末尾写“@课 id”链接到那一课，写“@课程 id”链接到那门课的导图。

function parseMap(text) {
  const root = { title: "", children: [] };
  const stack = [{ depth: -1, node: root }];
  for (const line of text.replace(/\r/g, "").split("\n")) {
    const h = line.match(/^#\s+(.+)/);
    if (h) { root.title = h[1].trim(); continue; }
    const m = line.match(/^(\s*)[-*]\s+(.+)$/);
    if (!m) continue;
    const depth = Math.floor(m[1].replace(/\t/g, "  ").length / 2);
    const refs = [];
    const title = m[2].replace(/\s+@([\w-]+)/g, (_, r) => (refs.push(r), "")).trim();
    const node = { title, ref: refs[0], children: [] };
    while (stack[stack.length - 1].depth >= depth) stack.pop();
    stack[stack.length - 1].node.children.push(node);
    stack.push({ depth, node });
  }
  return root;
}

// name：maps/ 下的文件名（不带 .txt）；extra(node)：额外的链接规则，比如课里的节点跳到对应小节
async function showMap(host, index, all, name, opts = {}, extra = null) {
  let text;
  try { text = await content(`course/maps/${name || "all"}.txt`); } catch {
    host.innerHTML = `<div class="empty small">这张导图还没有写好</div>`;
    return;
  }
  const p = progress();
  const lessons = Object.fromEntries(all.map((l) => [l.id, l]));
  const courses = Object.fromEntries(index.courses.map((c) => [c.id, c]));
  const root = parseMap(text);
  (function link(n) {
    if (n.ref && lessons[n.ref]) {
      const l = lessons[n.ref];
      n.href = `#/learn/${l.id}`;
      n.hrefTitle = `${l.course.title} · 第 ${l.no} 课：${l.title}`;
      n.done = !!p.done[l.id];
    } else if (n.ref && courses[n.ref]) {
      const c = courses[n.ref];
      n.href = `#/learn/map/${c.id}`;
      n.hrefTitle = `${c.title}的知识导图`;
      n.done = c.lessons.every((l) => p.done[l.id]);
    } else if (extra) extra(n);
    n.children.forEach(link);
  })(root);
  host.classList.add("lmap");
  return mountMindMap(host, [root], { title: root.title, ...opts });
}

async function mapPage(el, index, all, cid) {
  const course = cid && index.courses.find((c) => c.id === cid);
  if (cid && !course) cid = "";
  el.innerHTML = `
    <div class="row mb"><a class="btn sm ghost" href="#/learn">← 全部课程</a>
      ${course ? `<a class="btn sm ghost" href="#/learn/${course.id}">${esc(course.title)} · 课程目录</a>` : ""}</div>
    <div class="page-head"><div><div class="eyebrow">系统教程 · 知识导图</div>
      <h1>${course ? `${esc(course.icon)} ${esc(course.title)}` : "公考知识总导图"}</h1>
      <p>${course ? `这门课 ${course.lessons.length} 节课的全部知识点：一级是板块，往下是方法、公式和必记结论。点节点展开或收起，点 → 进入讲这个知识点的课。`
        : "从报考到上岸的全局：笔试（行测六大模块 + 申论）、面试、备考与考场策略。点 → 进入各模块的详细导图。"}</p></div></div>
    <div class="lmap-tabs"><a href="#/learn/map" class="${course ? "" : "on"}">总导图</a>${index.courses.map((c) =>
      `<a href="#/learn/map/${c.id}" class="${c === course ? "on" : ""}">${esc(c.icon)} ${esc(c.title)}</a>`).join("")}</div>
    <div class="card"><div id="map"></div>
      <div class="small muted lmap-note">拖动平移 · Ctrl + 滚轮缩放 · 点节点展开 / 收起 · “全屏”看大图 · ✓ 表示对应的课已学完</div></div>`;
  return showMap(el.querySelector("#map"), index, all, course?.id, { open: 2 });
}

// ---------------------------------------------------------------- 课

async function lessonPage(el, index, all, lesson) {
  const course = lesson.course;
  let text;
  try { text = await content(`course/${lesson.id}.md`); } catch {
    el.innerHTML = `<div class="card empty"><h3>这一课还在编写中</h3><a href="#/learn/${course.id}">返回课程</a></div>`;
    return;
  }
  const p = progress();
  p.last = lesson.id;
  const st = p.lessons[lesson.id] = p.lessons[lesson.id] || {};
  saveProgress(p);
  const parts = parseLesson(text);
  const opened = Date.now();
  const cleanups = [];
  const lctx = {
    lid: lesson.id, st, lesson, course, cleanups,
    save: () => saveProgress(p),
    onScore: () => drawScore(),
  };
  const idx = all.findIndex((l) => l.id === lesson.id);
  const prev = all[idx - 1], next = all[idx + 1];

  el.innerHTML = `
    <div class="lesson-layout">
      <aside class="lesson-side">
        <a class="small" href="#/learn/${course.id}">← ${esc(course.title)}</a>
        <a class="small ls-map" href="#/learn/map/${course.id}">本门课知识导图</a>
        <div class="progress mt"><i style="width:${courseStat(course, p).pct}%"></i></div>
        <ol class="ls-list">${course.lessons.map((l) => `<li class="${l.id === lesson.id ? "cur" : ""} ${p.done[l.id] ? "done" : ""}">
          <a href="#/learn/${l.id}">${esc(l.title)}</a></li>`).join("")}</ol>
      </aside>
      <nav class="float-toc" id="toc" aria-label="本课目录"></nav>
      <div class="lesson-main">
        <div class="lesson-head">
          <div class="eyebrow">${esc(course.title)} · 第 ${lesson.no} 课 · 约 ${lesson.min} 分钟</div>
          <h1>${esc(lesson.title)}</h1>
        </div>
        <details class="card lesson-map" id="lmapbox"${store.get("lessonMap", true) ? " open" : ""}>
          <summary><b>本课思维导图</b><span class="small muted">先看全貌，学完再回来对照复习 · 点带 → 的节点跳到课文对应的小节</span></summary>
          <div id="lmap"></div></details>
        <article class="card prose lesson-body" id="body">${renderParts(parts, lctx)}</article>
        <div class="card lesson-foot">
          <div class="row"><span id="score" class="ink2"></span><span class="spacer"></span>
            <span id="donebox"></span></div>
          <div class="row mt">
            ${prev ? `<a class="btn sm ghost" href="#/learn/${prev.id}">← ${esc(prev.title)}</a>` : ""}
            <span class="spacer"></span>
            ${next ? `<a class="btn sm" href="#/learn/${next.id}">下一课：${esc(next.title)} →</a>` : ""}
          </div>
        </div>
        <div class="card">
          <div class="card-head"><h3>我的笔记</h3><span class="small muted" id="nsaved"></span></div>
          <textarea id="note" rows="4" placeholder="记下这一课你最需要记住的东西、没弄懂的地方">${esc(st.note || "")}</textarea>
          <div class="row mt"><input type="text" id="askq" placeholder="有没弄懂的地方？写下问题，请 AI 结合这一课讲解" style="flex:1"></div>
          <div class="mt" id="ask"></div>
        </div>
      </div>
    </div>`;

  const body = el.querySelector("#body");
  bindParts(body, parts, lctx);
  // 本课目录：右侧悬浮，平时只显示短横线，鼠标移上去展开（仿 Notion）
  const hs = [...body.querySelectorAll("h2, h3")];
  hs.forEach((h, i) => (h.id = "s" + i));
  const toc = el.querySelector("#toc");
  if (hs.length > 1) {
    toc.innerHTML = `<div class="ft-rail">${hs.map((h) => `<i class="${h.tagName === "H3" ? "sub" : ""}"></i>`).join("")}</div>
      <div class="ft-panel">${hs.map((h, i) =>
        `<button data-h="${i}" class="${h.tagName === "H3" ? "sub" : ""}">${esc(h.textContent)}</button>`).join("")}</div>`;
    toc.querySelectorAll("[data-h]").forEach((b) => (b.onclick = () => hs[+b.dataset.h].scrollIntoView({ behavior: "smooth", block: "start" })));
    // 当前读到的小节高亮
    const view = document.getElementById("view");
    const dashes = toc.querySelectorAll(".ft-rail i"), btns = toc.querySelectorAll(".ft-panel button");
    let raf = 0;
    const spy = () => {
      raf = 0;
      const line = view.getBoundingClientRect().top + 100;
      let cur = 0;
      hs.forEach((h, i) => { if (h.getBoundingClientRect().top <= line) cur = i; });
      if (view.scrollTop + view.clientHeight >= view.scrollHeight - 4) cur = hs.length - 1;
      dashes.forEach((d, i) => d.classList.toggle("on", i === cur));
      btns.forEach((b, i) => b.classList.toggle("on", i === cur));
    };
    const onScroll = () => { if (!raf) raf = requestAnimationFrame(spy); };
    view.addEventListener("scroll", onScroll, { passive: true });
    cleanups.push(() => { view.removeEventListener("scroll", onScroll); cancelAnimationFrame(raf); });
    spy();
  } else toc.remove();

  // 本课思维导图（maps/lessons/<课 id>.txt）：展开时才排版（收起时量不出节点大小）；
  // 节点和课文里的小标题同名（不计“一、”“1.”这类序号）时，点 → 滚到那一节
  const norm = (t) => t.replace(/^\s*(?:[一二三四五六七八九十]+、|\d+[.、．]|（[一二三四五六七八九十]+）)/, "")
    .replace(/（[^）]*）|\([^)]*\)/g, "").replace(/[\s“”"'：:，,、。（）()·—\-]/g, "");
  // k：整个小标题；k2：冒号前那半截（“多空题：先做最有把握的空”→“多空题”）
  const heads = hs.map((h) => ({ h, k: norm(h.textContent), k2: norm(h.textContent.split(/[：:]/)[0]) }));
  const findHead = (t) => {
    const k = norm(t);
    if (k.length < 2) return null;
    return (heads.find((x) => x.k === k || x.k2 === k) || heads.find((x) => k.length >= 4 && x.k.startsWith(k)))?.h || null;
  };
  const mapBox = el.querySelector("#lmapbox");
  const mapName = `lessons/${lesson.id}`;
  let mapOn = false;
  const showLessonMap = async () => {
    if (mapOn || !mapBox.open) return;
    mapOn = true;
    const stop = await showMap(el.querySelector("#lmap"), index, all, mapName, {}, (n) => {
      const h = n.title !== lesson.title && findHead(n.title);
      if (h) {
        n.go = () => h.scrollIntoView({ behavior: "smooth", block: "start" });
        n.hrefTitle = "跳到课文：" + h.textContent;
      }
    });
    if (stop) cleanups.push(stop);
  };
  content(`course/maps/${mapName}.txt`).then(() => {
    mapBox.addEventListener("toggle", () => { store.set("lessonMap", mapBox.open); showLessonMap(); });
    showLessonMap();
  }, () => mapBox.remove());

  function drawScore() {
    const sc = scoreOf(st);
    const n = parts.filter((x) => ["quiz", "fill", "order", "match", "drill"].includes(x.type)).length;
    el.querySelector("#score").innerHTML = sc.n
      ? `随堂练习：做了 ${sc.n} 题，对 ${sc.ok} 题（${Math.round((sc.ok / sc.n) * 100)}%）`
      : n ? "本课有随堂练习，边学边做效果更好" : "";
  }
  function drawDone() {
    const box = el.querySelector("#donebox");
    const link = PRACTICE_LINK[course.module];
    box.innerHTML = p.done[lesson.id]
      ? `<span class="chip good">已于 ${esc(p.done[lesson.id])} 学完</span> <button class="btn sm ghost" id="undo">标为未学</button>`
      : `<button class="btn primary" id="done">学完了，记录 ${lesson.min} 分钟</button>`;
    if (link && p.done[lesson.id]) box.insertAdjacentHTML("beforeend", ` <a class="btn sm" href="${link}">去练习</a>`);
    const d = box.querySelector("#done");
    if (d) d.onclick = async () => {
      const mod = course.module;
      try { await apiPost("/api/study_log", { module: mod, minutes: lesson.min, source: "教程" }); } catch { /* 记时长失败不影响标记 */ }
      p.done[lesson.id] = new Date().toLocaleDateString("zh-CN");
      saveProgress(p);
      toast(next ? "这一课学完了，记忆卡已加入“教程知识卡”" : "全部课程学完了！");
      drawDone();
    };
    const u = box.querySelector("#undo");
    if (u) u.onclick = () => { delete p.done[lesson.id]; saveProgress(p); drawDone(); };
  }
  drawScore();
  drawDone();

  let nt = null;
  el.querySelector("#note").oninput = (e) => {
    clearTimeout(nt);
    nt = setTimeout(() => { st.note = e.target.value; saveProgress(p); el.querySelector("#nsaved").textContent = "已保存"; }, 600);
  };
  mountAIBox(el.querySelector("#ask"), {
    label: "就这一课问 AI",
    kind: "lesson",
    getBody: () => {
      const q = el.querySelector("#askq").value.trim();
      if (!q) throw new Error("先在上面写下你的问题");
      return { title: lesson.title, course: course.title, text, question: q };
    },
  });

  return () => {
    cleanups.forEach((f) => f());
    // 停留超过 3 分钟、还没标记学完的课，按实际时间记进学习时长（不重复记已学完的课）
    const minutes = Math.round((Date.now() - opened) / 60000);
    if (!p.done[lesson.id] && minutes >= 3) {
      apiPost("/api/study_log", { module: course.module, minutes: Math.min(minutes, 90), source: "教程" }).catch(() => {});
    }
  };
}
