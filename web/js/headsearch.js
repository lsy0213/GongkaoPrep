// 页头右上角的小搜索框（系统教程、资料库共用）：边打字边搜，结果在框下方浮层里；Ctrl+K 聚焦，↑↓ 选、回车打开、Esc 关
import { esc } from "./lib.js";

export function headSearchBox(placeholder, label) {
  return `<div class="head-search" id="hs">
      <form id="sf" role="search" class="hs-field">
        <span class="hs-ico" aria-hidden="true">⌕</span>
        <input type="search" id="sq" placeholder="${esc(placeholder)}" autocomplete="off" aria-label="${esc(label)}">
        <kbd>Ctrl K</kbd>
      </form>
      <div class="hs-pop" id="sr" hidden></div>
    </div>`;
}

// 把关键词转成高亮用的正则（文本已经 esc 过，所以关键词也先 esc）
export function hlRegex(q) {
  const terms = q.split(/\s+/).filter(Boolean).map((t) => esc(t).replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  return new RegExp(terms.join("|") || "(?!)", "gi");
}

// hot：空输入时给的常搜词；run(q) 返回浮层 HTML，可点的结果带 data-go。返回解绑函数
export function bindHeadSearch(el, { hot, run }) {
  const box = el.querySelector("#hs");
  const sq = el.querySelector("#sq");
  const pop = el.querySelector("#sr");
  let timer = 0, seq = 0, cur = -1;

  const items = () => [...pop.querySelectorAll("[data-go]")];
  const mark = (i) => {
    const xs = items();
    cur = xs.length ? (i + xs.length) % xs.length : -1;
    xs.forEach((x, j) => x.classList.toggle("on", j === cur));
    xs[cur]?.scrollIntoView({ block: "nearest" });
  };
  const open = () => { pop.hidden = false; box.classList.add("open"); };
  const close = () => { pop.hidden = true; box.classList.remove("open"); cur = -1; };
  const showHot = () => {
    seq++;
    pop.innerHTML = `<div class="hs-label">常搜</div><div class="hs-tags">${hot.map((w) => `<button type="button" class="chip" data-q="${esc(w)}">${esc(w)}</button>`).join("")}</div>`;
    open();
  };
  const search = async (q) => {
    const my = ++seq;
    if (!q) return showHot();
    pop.innerHTML = `<div class="hs-label">搜索中…</div>`;
    open();
    let html;
    try { html = await run(q); } catch (e) { html = `<div class="hs-empty">搜索出错：${esc(e.message)}</div>`; }
    if (my !== seq) return;
    pop.innerHTML = html;
    cur = -1;
  };

  sq.addEventListener("focus", () => (sq.value.trim() ? search(sq.value.trim()) : showHot()));
  sq.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => search(sq.value.trim()), 220); });
  sq.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); mark(cur + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); mark(cur - 1); }
    else if (e.key === "Escape") { if (sq.value) { sq.value = ""; showHot(); } else { close(); sq.blur(); } e.preventDefault(); }
  });
  el.querySelector("#sf").onsubmit = (e) => {
    e.preventDefault();
    const xs = items();
    if (xs.length) xs[Math.max(cur, 0)].click();
    else { clearTimeout(timer); search(sq.value.trim()); }
  };
  pop.addEventListener("mousedown", (e) => e.preventDefault()); // 点浮层时不让输入框失焦
  pop.addEventListener("click", (e) => {
    const t = e.target.closest("[data-q]");
    if (t) { sq.value = t.dataset.q; search(t.dataset.q); }
  });
  sq.addEventListener("blur", () => setTimeout(close, 120));
  const onKey = (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k" && sq.isConnected) { e.preventDefault(); sq.focus(); sq.select(); }
  };
  document.addEventListener("keydown", onKey);
  return () => { clearTimeout(timer); seq++; document.removeEventListener("keydown", onKey); };
}
