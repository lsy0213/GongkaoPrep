// 思维导图：把提纲树排成从左到右展开的导图（根节点在左，分支按颜色区分，曲线连接）。
// 操作：按住拖动平移（节点上也能拖）；Ctrl+滚轮 / 触控板捏合缩放；滚轮在导图里还能往下看就先滚导图，到头了接着滚正文；
// 点有下级的节点展开 / 收起；双击空白处适应窗口；“全屏”在大窗口里看，Esc 退出。
// 节点可带 href 或 go（函数，比如滚到课文的某一节）：后面出现“→”，点它跳转；没有下级的节点点整个节点也跳转。done 打勾。
import { esc } from "./lib.js";

const PAD = 26;
const GAP_X = [44, 34, 26]; // 根→一级、一级→二级、更深
const GAP_Y = [16, 10, 6]; // 一级之间、二级之间、更深
const MIN_S = 0.35, MAX_S = 2.2;
const gapX = (depth) => GAP_X[Math.min(depth, GAP_X.length - 1)];
const gapY = (depth) => GAP_Y[Math.min(depth - 1, GAP_Y.length - 1)];
const boxy = (n) => n.depth <= 1; // 根和一级是方框，下面几级是“文字 + 下划线”

export function mountMindMap(host, roots, { title = "思维导图", open } = {}) {
  const root = roots.length === 1 ? roots[0] : { title, children: roots, virtual: true };
  let count = 0;
  (function prep(n, depth, branch) {
    n.depth = depth;
    n.branch = branch;
    n.id = count++;
    n.children.forEach((c, i) => prep(c, depth + 1, depth === 0 ? i % 6 : branch));
  })(root, 0, 0);
  const all = [];
  (function walk(n) { all.push(n); n.children.forEach(walk); })(root);
  const openTo = (lv) => all.forEach((n) => (n.open = n.depth < lv));
  openTo(open ?? (count <= 40 ? 99 : 2));

  // 控制条放在导图上方（阅读器里和“导图 / 文字提纲”同一行），不挡节点
  host.innerHTML = `<div class="mm">
    <div class="mm-ctl">
      <span class="mm-hint">拖动平移 · Ctrl+滚轮缩放 · 点节点展开/收起</span>
      <button type="button" data-mm="out" title="缩小">−</button><button type="button" data-mm="fit" class="mm-scale" title="适应窗口（也可以双击空白处）">100%</button><button type="button" data-mm="in" title="放大">+</button>
      <span class="mm-sep"></span>
      <button type="button" data-mm="all" title="展开 / 收起全部分支">全部收起</button>
      <button type="button" data-mm="full" title="在大窗口里看">全屏</button>
    </div>
    <div class="mm-view"><div class="mm-stage"><svg class="mm-links" aria-hidden="true"></svg><div class="mm-nodes"></div></div></div>
  </div>`;
  const box = host.querySelector(".mm");
  const view = box.querySelector(".mm-view");
  const stage = box.querySelector(".mm-stage");
  const svg = box.querySelector(".mm-links");
  const layer = box.querySelector(".mm-nodes");
  const scaleBtn = box.querySelector(".mm-scale");
  const allBtn = box.querySelector('[data-mm="all"]');
  const fullBtn = box.querySelector('[data-mm="full"]');

  let s = 1, tx = 0, ty = 0, W = 0, H = 0;
  let full = false;

  function nodeEl(n) {
    if (n.el) return n.el;
    const el = document.createElement("div");
    el.className = `mm-node d${Math.min(n.depth, 3)}${n.children.length ? " has-kids" : ""}${n.virtual ? " virtual" : ""}${n.href || n.go ? " linked" : ""}${n.done ? " done" : ""}`;
    el.style.setProperty("--c", `var(--mm-${n.branch + 1})`);
    el.innerHTML = `<span class="mm-t">${esc(n.title)}</span>${n.done ? `<i class="mm-done" title="已学完">✓</i>` : ""}`
      + (n.href ? `<a class="mm-go" href="${esc(n.href)}" draggable="false" title="${esc(n.hrefTitle || "打开")}">→</a>`
        : n.go ? `<a class="mm-go" role="button" draggable="false" title="${esc(n.hrefTitle || "跳到这里")}">→</a>` : "")
      + (n.children.length ? `<i class="mm-tog"></i>` : "");
    el.dataset.id = n.id;
    return (n.el = el);
  }

  const shown = () => {
    const out = [];
    (function walk(n) { out.push(n); if (n.open) n.children.forEach(walk); })(root);
    return out;
  };

  function size(n) {
    const kids = n.open ? n.children : [];
    if (!kids.length) return (n.sh = n.h);
    let sum = gapY(n.depth + 1) * (kids.length - 1);
    kids.forEach((c) => (sum += size(c)));
    return (n.sh = Math.max(n.h, sum));
  }

  function place(n, x, top) {
    n.x = x;
    n.y = top + (n.sh - n.h) / 2;
    const kids = n.open ? n.children : [];
    if (!kids.length) return;
    const gap = gapY(n.depth + 1);
    const total = kids.reduce((a, c) => a + c.sh, 0) + gap * (kids.length - 1);
    let y = top + (n.sh - total) / 2;
    const cx = x + n.w + gapX(n.depth);
    for (const c of kids) { place(c, cx, y); y += c.sh + gap; }
  }

  const outPt = (n) => [n.x + n.w, boxy(n) ? n.y + n.h / 2 : n.y + n.h - 1];
  const inPt = (n) => [n.x, boxy(n) ? n.y + n.h / 2 : n.y + n.h - 1];

  function render() {
    const list = shown();
    layer.replaceChildren(...list.map(nodeEl));
    for (const n of list) {
      if (n.w == null) { n.w = n.el.offsetWidth; n.h = n.el.offsetHeight; }
      n.el.classList.toggle("closed", !n.open && n.children.length > 0);
      const tog = n.el.querySelector(".mm-tog");
      if (tog) tog.textContent = n.open ? "−" : String(n.children.length);
    }
    size(root);
    place(root, PAD, PAD);
    W = 0;
    for (const n of list) {
      W = Math.max(W, n.x + n.w);
      n.el.style.transform = `translate(${n.x}px, ${n.y}px)`;
    }
    W += PAD + 10;
    H = root.sh + PAD * 2;
    // 根→一级用平滑曲线；再往下每个父节点一根竖“主干”，圆角拐进各个子节点——下级再多、再长也不会拉出一片斜线
    let paths = "";
    for (const n of list) {
      if (!n.open || !n.children.length) continue;
      const [x1, y1] = outPt(n);
      const lv = Math.min(n.depth, 2);
      for (const c of n.children) {
        const [x2, y2] = inPt(c);
        let d;
        if (n.depth === 0) {
          const mx = x1 + (x2 - x1) * 0.55;
          d = `M${x1} ${y1}C${mx} ${y1} ${x1 + (x2 - x1) * 0.45} ${y2} ${x2} ${y2}`;
        } else {
          const kx = x1 + Math.min(14, (x2 - x1) / 2);
          const r = Math.min(8, Math.abs(y2 - y1) / 2, x2 - kx);
          d = r < 1 ? `M${x1} ${y1}H${kx}V${y2}H${x2}`
            : `M${x1} ${y1}H${kx}V${y2 - Math.sign(y2 - y1) * r}Q${kx} ${y2} ${kx + r} ${y2}H${x2}`;
        }
        paths += `<path d="${d}" class="l${lv}" style="--c:var(--mm-${c.branch + 1})"/>`;
      }
    }
    svg.setAttribute("width", W);
    svg.setAttribute("height", H);
    svg.innerHTML = paths;
    stage.style.width = W + "px";
    stage.style.height = H + "px";
    const anyClosed = all.some((n) => n.depth > 0 && n.children.length && !n.open);
    allBtn.textContent = anyClosed ? "全部展开" : "全部收起";
  }

  // ---------------------------------------------------------------- 视图
  function clamp() {
    const vw = view.clientWidth, vh = view.clientHeight, cw = W * s, ch = H * s;
    // 放得下的方向居中不动（滚轮直接交给正文），放不下的方向不许拖出边
    tx = cw <= vw ? (vw - cw) / 2 : Math.min(Math.max(tx, vw - cw), 0);
    ty = ch <= vh ? (vh - ch) / 2 : Math.min(Math.max(ty, vh - ch), 0);
  }
  function apply() {
    clamp();
    stage.style.transform = `translate(${tx}px, ${ty}px) scale(${s})`;
    scaleBtn.textContent = Math.round(s * 100) + "%";
  }
  function zoomAt(px, py, ns) {
    ns = Math.max(MIN_S, Math.min(MAX_S, ns));
    tx = px - ((px - tx) * ns) / s;
    ty = py - ((py - ty) * ns) / s;
    s = ns;
    apply();
  }
  // 适应窗口：能整张放下就整张放下（不放大超过 100%）；整张放下字会小到看不清时，保持能读的大小、从根节点开始看。
  // whole = true（点比例按钮 / 双击空白）：不管多小都整张放下，看全貌
  function fit(whole = false) {
    const vw = view.clientWidth, vh = view.clientHeight;
    s = Math.max(MIN_S, Math.min(full ? 1.15 : 1, (vw - 8) / W, (vh - 8) / H));
    const readable = full ? 0.9 : 0.8;
    if (!whole && s < readable * 0.85) s = readable; // 差一点就能整张放下时宁可略小一点，省得要拖
    tx = W * s <= vw ? (vw - W * s) / 2 : 0;
    ty = H * s <= vh ? (vh - H * s) / 2 : vh / 2 - (root.y + root.h / 2) * s;
    apply();
  }
  // 正文里的导图高度：按内容定，最高占屏幕七成；只增不减，避免展开收起时页面跳动
  let viewH = 0;
  function sizeView() {
    if (full) return;
    const maxH = Math.max(260, Math.min(680, window.innerHeight * 0.7));
    viewH = Math.max(viewH, Math.round(Math.min(maxH, Math.max(200, H * s + 12))));
    view.style.height = viewH + "px";
  }

  // 展开 / 收起时，点的那个节点留在屏幕原处
  function relayout(anchor) {
    const before = anchor && [tx + anchor.x * s, ty + anchor.y * s];
    render();
    sizeView();
    if (before) { tx = before[0] - anchor.x * s; ty = before[1] - anchor.y * s; }
    apply();
  }

  function setFull(on) {
    full = on;
    box.classList.toggle("mm-full", on);
    fullBtn.textContent = on ? "退出全屏" : "全屏";
    view.style.height = on ? "" : viewH + "px";
    fit();
  }

  box.querySelector(".mm-ctl").addEventListener("click", (e) => {
    const act = e.target.closest("[data-mm]")?.dataset.mm;
    const cx = view.clientWidth / 2, cy = view.clientHeight / 2;
    if (act === "in") zoomAt(cx, cy, s * 1.2);
    else if (act === "out") zoomAt(cx, cy, s / 1.2);
    else if (act === "fit") fit(true);
    else if (act === "full") setFull(!full);
    else if (act === "all") {
      const anyClosed = all.some((n) => n.depth > 0 && n.children.length && !n.open);
      openTo(anyClosed ? 99 : 1);
      viewH = 0;
      render();
      sizeView();
      fit();
    }
  });

  // 拖动：移动超过几像素才算拖，没拖就是点击（点节点 = 展开 / 收起）
  let drag = null;
  view.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || e.target.closest(".mm-ctl")) return;
    drag = { x: e.clientX, y: e.clientY, tx, ty, moved: false, target: e.target, id: e.pointerId };
  });
  view.addEventListener("pointermove", (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (!drag.moved) {
      if (Math.hypot(dx, dy) < 4) return;
      drag.moved = true;
      view.setPointerCapture(e.pointerId);
      view.classList.add("dragging");
    }
    tx = drag.tx + dx;
    ty = drag.ty + dy;
    apply();
  });
  const endDrag = (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    const d = drag;
    drag = null;
    view.classList.remove("dragging");
    if (d.moved || e.type === "pointercancel") return;
    const el = d.target.closest?.(".mm-node");
    if (!el) return;
    const n = all[+el.dataset.id];
    const go = () => (n.href ? (location.hash = n.href) : n.go?.());
    if (d.target.closest(".mm-go")) {
      if (!n.href) { if (full) setFull(false); go(); } // href 的链接交给浏览器自己跳
      return;
    }
    if (!n.children.length) { if (full && n.go) setFull(false); go(); return; }
    n.open = !n.open;
    relayout(n);
  };
  view.addEventListener("pointerup", endDrag);
  view.addEventListener("pointercancel", endDrag);
  view.addEventListener("dblclick", (e) => {
    if (!e.target.closest(".mm-node, .mm-ctl")) fit(true);
  });

  // 滚轮：Ctrl 缩放；否则导图还能往那个方向挪就挪导图，挪到头了交给正文滚动
  view.addEventListener("wheel", (e) => {
    const r = view.getBoundingClientRect();
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      zoomAt(e.clientX - r.left, e.clientY - r.top, s * Math.exp(-e.deltaY * (e.deltaMode ? 0.05 : 0.0018)));
      return;
    }
    const k = e.deltaMode === 1 ? 32 : e.deltaMode === 2 ? view.clientHeight : 1;
    let dx = e.deltaX * k, dy = e.deltaY * k;
    if (e.shiftKey && !dx) { dx = dy; dy = 0; }
    const ox = tx, oy = ty;
    tx -= dx;
    ty -= dy;
    apply();
    if (tx !== ox || ty !== oy || full) e.preventDefault();
  }, { passive: false });

  const onKey = (e) => { if (full && e.key === "Escape") { e.stopPropagation(); setFull(false); } };
  document.addEventListener("keydown", onKey, true);
  const ro = new ResizeObserver(() => apply());
  ro.observe(view);

  render();
  sizeView();
  fit();

  return () => {
    document.removeEventListener("keydown", onKey, true);
    ro.disconnect();
  };
}
