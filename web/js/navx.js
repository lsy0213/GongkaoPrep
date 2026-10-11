// 手机底部导航（和 EngNest 一样的液态玻璃胶囊）：首页 / 刷题 / 闪卡 / 时政 / 更多，选中项下面有一块会滑动的「镜片」；
// 「更多」打开侧栏抽屉。侧栏菜单也换成同一套细线图标（白瓷星轨里显示，珍藏手稿仍用原来的字形）。
import { icon } from "./icons.js";
import { EXAM, esc } from "./lib.js";

const MORE = `<circle cx="5.5" cy="12" r="1.35" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.35" fill="currentColor" stroke="none"/><circle cx="18.5" cy="12" r="1.35" fill="currentColor" stroke="none"/>`;
// [路由, 名称, 图标, 哪些页面算这一项]：来自考试清单的 bottom_nav（app.js 先 initExam 再用到这里）
const DEFAULT_BOTTOM = [["", "首页", "home", [""]]];
const bottomNav = () => EXAM.cur?.bottom_nav || DEFAULT_BOTTOM;

const bar = document.getElementById("bottom-nav");

// 侧栏菜单项：在原来的字形旁边放一个细线图标（app.js 按清单生成菜单后调用）
export function decorateNav() {
  for (const a of document.querySelectorAll("#nav a.nav-item[data-route]")) {
    if (a.querySelector(".ico-ln")) continue;
    const svg = icon(a.dataset.route || "home");
    if (svg) a.querySelector(".ico")?.insertAdjacentHTML("afterend", `<span class="ico-ln">${svg}</span>`);
  }
}

function build() {
  bar.innerHTML = `<span class="bn-lens" aria-hidden="true"></span>`
    + bottomNav().map(([r, label, ico]) => `<a class="bn-item" href="#/${r}" data-bn="${r}"><span class="bn-ico">${icon(ico)}</span><span class="bn-label">${esc(label)}</span></a>`).join("")
    + `<button class="bn-item" id="bn-more" type="button" aria-label="更多功能"><span class="bn-ico"><svg class="ln-ico" viewBox="0 0 24 24" aria-hidden="true">${MORE}</svg></span><span class="bn-label">更多</span></button>`;
  bar.querySelector("#bn-more").onclick = () => document.body.classList.add("nav-open");
}

// 镜片移到选中的那一项下面（没有选中的就藏起来）
function placeLens() {
  const lens = bar?.querySelector(".bn-lens"), act = bar?.querySelector(".bn-item.active");
  if (!lens) return;
  if (!act || !act.offsetWidth) { lens.classList.remove("on"); return; }
  const w = Math.min(act.offsetWidth - 4, 76);
  lens.style.width = `${w}px`;
  lens.style.transform = `translateX(${act.offsetLeft + (act.offsetWidth - w) / 2}px)`;
  lens.classList.add("on");
}

// 换页面时调用：只改选中项和角标，不重建（重建会把液态玻璃的 canvas 一起扔掉，iPhone 上内存吃紧）
export function syncBottomNav(route) {
  if (!bar) return;
  if (!bar.querySelector(".bn-item")) build();
  for (const [r, , , pages] of bottomNav()) bar.querySelector(`[data-bn="${r}"]`)?.classList.toggle("active", pages.includes(route));
  placeLens();
  RealGlass.start();
}

// 刷题（没有刷题的考试就是错题）上的小红点：到期要重做的错题数
export function setBottomBadge(n) {
  const ico = (bar?.querySelector('[data-bn="practice"]') || bar?.querySelector('[data-bn="wrong"]'))?.querySelector(".bn-ico");
  if (!ico) return;
  let b = ico.querySelector(".bn-badge");
  if (n && !b) b = ico.appendChild(Object.assign(document.createElement("i"), { className: "bn-badge" }));
  if (b) { if (n) b.textContent = n > 99 ? "99+" : n; else b.remove(); }
}

window.addEventListener("resize", placeLens);

// 真正的液态玻璃（会折射后面的内容）：apple-liquid-glass-webgl（MIT，vendor/liquid-glass/）用 WebGL2 把底栏后面重画一遍再弯折。
// 只在手机宽度加载；不支持 WebGL2 或加载失败时，CSS 的毛玻璃照样在（.liquid-glass）
const NARROW = window.matchMedia?.("(max-width: 560px)");
const RealGlass = {
  started: false,
  // 玻璃后面只画页面底色和一层柔光，不去扫描整个页面（滚动、换页时不用重画，手机上不卡）
  backdrop(ctx, r) {
    const css = getComputedStyle(document.documentElement);
    const bg = css.getPropertyValue("--bg").trim() || "#eee", surf = css.getPropertyValue("--surface").trim() || bg;
    ctx.fillStyle = bg;
    ctx.fillRect(r.x, r.y, r.width, r.height);
    const g = ctx.createLinearGradient(0, r.y, 0, r.y + r.height);
    g.addColorStop(0, surf);
    g.addColorStop(1, bg);
    ctx.globalAlpha = 0.7;
    ctx.fillStyle = g;
    ctx.fillRect(r.x, r.y, r.width, r.height);
    ctx.globalAlpha = 1;
  },
  start() {
    if (this.started || !NARROW?.matches || window.matchMedia("(prefers-reduced-transparency: reduce)").matches) return;
    this.started = true;
    const s = document.createElement("script");
    s.src = "/vendor/liquid-glass/liquid-glass.min.js";
    s.onload = () => {
      const LG = window.LiquidGlass;
      if (!LG?.isSupported?.()) return;
      try {
        new LG("#bottom-nav", { backdrop: (ctx, r) => this.backdrop(ctx, r), tintTone: "auto", maxDpr: 2, fallback: "none",
          material: { backdropBlur: 4, tint: 0.3, dispersion: 1.2 } });
      } catch (e) { console.info("液态玻璃没开成：", e.message); }
    };
    document.head.appendChild(s);
  },
};
