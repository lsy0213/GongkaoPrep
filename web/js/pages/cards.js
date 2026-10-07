import { apiGet, apiPost, esc, mathText, shuffle, todayISO, toast } from "../lib.js";

const SESSION = 20;

export async function render(el) {
  // 内置卡组 + 从资料库背诵材料里生成的卡组
  const data = await apiGet("/api/decks");
  let state = {}, today = todayISO(), notes = [], memo = { books: [], items: [] };
  let keyHandler = null;

  async function load() {
    const [c, n, m] = await Promise.all([apiGet("/api/cards"), apiGet("/api/notebook"), apiGet("/api/memo")]);
    memo = m;
    state = Object.fromEntries(c.items.map((x) => [x.card_id, x]));
    today = c.today;
    notes = n.items;
  }

  function decks() {
    const mine = {
      id: "mine", name: "我的积累",
      cards: notes.map((n) => ({ id: "nb-" + n.id, front: n.title ? `${n.title}（${n.kind}）` : n.kind, back: n.content + (n.source ? `\n—— ${n.source}` : "") })),
    };
    // 笔记本：每个有内容的本子一个卡组，正面是标题，背面是内容和自己的笔记
    const memoDecks = memo.books.map((b) => ({
      id: "memo-" + b.id, name: "笔记本 · " + b.name, math: true,
      cards: memo.items.filter((x) => x.book === b.id).map((x) => ({
        id: "memo-" + x.id, math: true,
        front: x.title || (x.source ? `${x.source.split(" · ").pop()}里记的一条` : `「${b.name}」里的一条`),
        back: x.content + (x.note ? `\n✎ ${x.note}` : ""),
      })),
    })).filter((d) => d.cards.length);
    return [...data.decks, mine, ...memoDecks];
  }

  function stats(deck) {
    let fresh = 0, due = 0, learned = 0;
    for (const c of deck.cards) {
      const s = state[c.id];
      if (!s) fresh++;
      else if (s.due <= today) due++;
      if (s && s.box >= 3) learned++;
    }
    return { fresh, due, learned };
  }

  function home() {
    const ds = decks();
    const totalDue = ds.reduce((a, d) => a + stats(d).due, 0);
    el.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">闪卡记忆</div><h1>碎片时间刷闪卡</h1>
        <p>认识就升一级，复习间隔依次拉长到 1、3、7、14、30 天；不认识就回到第一级，明天再见。</p></div>
        <button class="btn primary lg" id="all" ${totalDue ? "" : "disabled"}>${totalDue ? `复习全部到期 ${totalDue} 张` : "今天没有到期的卡片"}</button></div>
      <div class="grid cols-3">
        ${ds.map((d) => {
          const s = stats(d);
          return `<button class="deck" data-deck="${d.id}" ${d.cards.length ? "" : "disabled"}>
            <b>${esc(d.name)}</b>
            <span class="small ink2">${d.cards.length} 张 · 已熟记 ${s.learned}</span>
            <span class="row small">${s.due ? `<span class="chip warn">到期 ${s.due}</span>` : ""}${s.fresh ? `<span class="chip">新卡 ${s.fresh}</span>` : ""}${!d.cards.length ? `<span class="chip">暂无卡片</span>` : !s.due && !s.fresh ? `<span class="chip good">今日完成</span>` : ""}</span>
            <span class="progress" style="width:100%"><i style="width:${d.cards.length ? (s.learned / d.cards.length) * 100 : 0}%"></i></span>
          </button>`;
        }).join("")}
      </div>
      <p class="small muted mt">“教程知识卡”收录你学完的教程课里的记忆卡；“我的积累”卡组来自“素材积累”里你自己添加的内容。${data.lib_count ? `另有 ${data.lib_count} 个卡组由资料库里的成语、常识等背诵材料自动生成。` : ""}</p>`;
    el.querySelectorAll("[data-deck]").forEach((b) => (b.onclick = () => {
      const d = ds.find((x) => x.id === b.dataset.deck);
      study(d.name, d.cards.map((c) => ({ ...c, deck: d.id })));
    }));
    const all = el.querySelector("#all");
    if (all) all.onclick = () => study("全部到期", ds.flatMap((d) => d.cards.map((c) => ({ ...c, deck: d.id }))).filter((c) => state[c.id] && state[c.id].due <= today));
  }

  function study(title, cards) {
    const due = shuffle(cards.filter((c) => state[c.id] && state[c.id].due <= today));
    const fresh = cards.filter((c) => !state[c.id]);
    let queue = due.concat(fresh).slice(0, SESSION);
    if (!queue.length) queue = shuffle(cards).slice(0, SESSION); // 全部背过了就随机抽查
    let i = 0, flipped = false, known = 0, busy = false;
    const results = new Map(); // card.id → { card, first, last, misses }，本轮结束时做回顾
    const t0 = Date.now();
    const OUT_MS = 340, IN_MS = 300, SWIPE_PX = 110;

    // 骨架只渲染一次，换卡时只替换内容，动画才能连贯
    el.innerHTML = `
      <div class="row mb"><button class="btn sm ghost" id="back">← 卡组</button><span class="spacer"></span>
        <span class="small muted num" id="count"></span></div>
      <div class="progress mb"><i id="bar"></i></div>
      <div class="flash">
        <div class="flash-stage">
          <div class="flash-card" id="card" tabindex="0" role="button" aria-label="翻面">
            <span class="flash-stamp no">不认识</span><span class="flash-stamp yes">认识</span>
            <div class="flash-inner">
              <div class="flash-face flash-front"><div class="front" id="qf"></div><div class="small muted mt">先在心里回答，再按空格或点击卡片翻面</div></div>
              <div class="flash-face flash-back"><div class="q" id="qb"></div><div class="back" id="ab"></div></div>
            </div>
          </div>
        </div>
        <div class="flash-actions">
          <button class="btn lg danger" id="no">← 不认识</button>
          <button class="btn lg" id="flip">翻面 <span class="kbd">空格</span></button>
          <button class="btn lg primary" id="yes">认识 →</button>
        </div>
        <p class="small muted flash-tip">空格 翻面 · ← 不认识 · → 认识 · 也可以翻面后直接把卡片左右拖走</p>
      </div>`;
    const card = el.querySelector("#card");
    const btnNo = el.querySelector("#no"), btnYes = el.querySelector("#yes");

    function setFlipped(v) {
      flipped = v;
      card.classList.toggle("flipped", v);
      btnNo.disabled = btnYes.disabled = !v;
    }

    function draw() {
      if (i >= queue.length) return finish();
      const c = queue[i];
      el.querySelector("#count").textContent = `${title} · ${i + 1} / ${queue.length}`;
      el.querySelector("#bar").style.width = `${(i / queue.length) * 100}%`;
      el.querySelector("#qf").textContent = c.front;
      el.querySelector("#qb").textContent = c.front;
      if (c.math) el.querySelector("#ab").innerHTML = mathText(c.back);
      else el.querySelector("#ab").textContent = c.back;
      setFlipped(false);
    }

    // 换卡：旧卡带着倾斜甩出去，新卡从下方浮上来（翻回正面的过程不做动画）
    function swapTo(dir, then) {
      busy = true;
      card.classList.remove("dragging");
      card.style.transform = "";
      card.classList.add(dir < 0 ? "out-left" : "out-right");
      setTimeout(() => {
        card.classList.add("no-anim");
        card.classList.remove("out-left", "out-right");
        card.classList.add("enter");
        then();
        void card.offsetWidth;
        card.classList.remove("no-anim", "enter");
        setTimeout(() => { busy = false; }, IN_MS);
      }, OUT_MS);
    }

    function answer(ok) {
      if (busy || !flipped) return;
      const c = queue[i];
      apiPost("/api/cards/review", { card_id: c.id, deck: c.deck, known: ok })
        .then((r) => { state[c.id] = { ...(state[c.id] || {}), box: r.box, due: r.due }; })
        .catch((e) => toast(e.message));
      const r = results.get(c.id) || { card: c, first: ok, misses: 0 };
      r.last = ok;
      if (!ok) r.misses++;
      results.set(c.id, r);
      if (ok) known++;
      else if (queue.filter((x) => x.id === c.id).length < 2) queue.push(c); // 不认识的本轮末尾再出现一次
      swapTo(ok ? 1 : -1, () => { i++; draw(); });
    }

    function flip() { if (!busy) setFlipped(!flipped); }

    // 拖拽：翻面后左右拖动，超过阈值即作答，否则弹回；几乎没动就当作点击翻面
    let drag = null;
    card.addEventListener("pointerdown", (e) => {
      if (busy || e.button !== 0) return;
      drag = { x: e.clientX, y: e.clientY, dx: 0, moved: false };
      try { card.setPointerCapture(e.pointerId); } catch {}
    });
    card.addEventListener("pointermove", (e) => {
      if (!drag) return;
      drag.dx = e.clientX - drag.x;
      if (!drag.moved && Math.hypot(drag.dx, e.clientY - drag.y) > 6) drag.moved = true;
      if (!drag.moved || !flipped) return;
      card.classList.add("dragging");
      card.style.transform = `translateX(${drag.dx}px) rotate(${drag.dx / 18}deg)`;
      const p = Math.min(Math.abs(drag.dx) / SWIPE_PX, 1);
      card.style.setProperty("--no", drag.dx < 0 ? p : 0);
      card.style.setProperty("--yes", drag.dx > 0 ? p : 0);
    });
    const endDrag = () => {
      if (!drag) return;
      const { dx, moved } = drag;
      drag = null;
      card.style.removeProperty("--no"); card.style.removeProperty("--yes");
      if (!moved) return flip();
      if (flipped && Math.abs(dx) >= SWIPE_PX) return answer(dx > 0);
      card.classList.remove("dragging");
      card.style.transform = "";
    };
    card.addEventListener("pointerup", endDrag);
    card.addEventListener("pointercancel", endDrag);

    el.querySelector("#back").onclick = () => { cleanupKeys(); load().then(home); };
    el.querySelector("#flip").onclick = flip;
    btnYes.onclick = () => answer(true);
    btnNo.onclick = () => answer(false);

    async function finish() {
      cleanupKeys();
      const min = Math.round((Date.now() - t0) / 60000);
      if (min >= 1) await apiPost("/api/study_log", { module: "积累", minutes: min, source: "闪卡" }).catch(() => {});
      const all = [...results.values()];
      const missed = all.filter((r) => r.misses).sort((a, b) => a.last - b.last || b.misses - a.misses); // 仍没记住的排前面
      const got = all.filter((r) => !r.misses);
      const still = missed.filter((r) => !r.last).length;
      const item = (r) => `<details class="recap-item${r.misses ? " miss" : ""}"><summary>
          <span class="recap-q">${esc(r.card.front)}</span>
          ${r.misses ? (r.last ? `<span class="chip good">第二遍记住了</span>` : `<span class="chip bad">仍不认识</span>`) : ""}</summary>
          <div class="recap-a">${r.card.math ? mathText(r.card.back) : esc(r.card.back)}</div></details>`;
      el.innerHTML = `
        <div class="page-head"><div><div class="eyebrow">本轮回顾 · ${esc(title)}</div><h1>${missed.length ? "把不认识的再过一眼" : "全部认识，漂亮"}</h1>
          <p>不认识的卡已回到第一级，明天会再出现；认识的按间隔往后排。</p></div></div>
        <div class="grid cols-4 mb">
          <div class="stat"><div class="v num">${all.length}<small>张</small></div><div class="k">本轮卡片</div></div>
          <div class="stat"><div class="v num">${got.length}<small>张</small></div><div class="k">一次认识</div></div>
          <div class="stat${missed.length ? " alert" : ""}"><div class="v num">${missed.length}<small>张</small></div><div class="k">不认识${missed.length ? `（仍没记住 ${still}）` : ""}</div></div>
          <div class="stat"><div class="v num">${min || "<1"}<small>分钟</small></div><div class="k">${min >= 1 ? "已记入学习时长" : "用时"}</div></div>
        </div>
        ${missed.length ? `<div class="card mb"><div class="row mb"><h3>不认识的 ${missed.length} 张</h3><span class="spacer"></span>
            <button class="btn sm ghost" data-toggle="miss">全部展开</button></div>
            <div class="recap" id="miss">${missed.map(item).join("")}</div></div>` : ""}
        ${got.length ? `<div class="card mb"><div class="row mb"><h3>认识的 ${got.length} 张</h3><span class="spacer"></span>
            <button class="btn sm ghost" data-toggle="got">全部展开</button></div>
            <div class="recap" id="got">${got.map(item).join("")}</div></div>` : ""}
        <div class="row">
          ${missed.length ? `<button class="btn primary" id="redo">再刷一遍不认识的 ${missed.length} 张</button>` : ""}
          <button class="btn${missed.length ? "" : " primary"}" id="again">回到卡组</button>
        </div>`;
      // 不认识的默认展开答案，直接就能复习
      el.querySelectorAll("#miss details").forEach((d) => (d.open = true));
      el.querySelectorAll("[data-toggle]").forEach((b) => {
        const ds = [...el.querySelectorAll(`#${b.dataset.toggle} details`)];
        const sync = () => (b.textContent = ds.every((d) => d.open) ? "全部收起" : "全部展开");
        ds.forEach((d) => d.addEventListener("toggle", sync));
        b.onclick = () => { const open = !ds.every((d) => d.open); ds.forEach((d) => (d.open = open)); sync(); };
        sync();
      });
      el.querySelector("#again").onclick = () => load().then(home);
      const redo = el.querySelector("#redo");
      if (redo) redo.onclick = () => study(`${title} · 错卡重刷`, missed.map((r) => r.card));
    }

    keyHandler = (e) => {
      if (/INPUT|TEXTAREA/.test(document.activeElement?.tagName)) return;
      if (e.code === "Space" || e.key === "Enter") {
        e.preventDefault();
        if (document.activeElement?.tagName === "BUTTON") document.activeElement.blur(); // 防止再触发一次聚焦的按钮
        flip();
      }
      else if (e.key === "ArrowLeft" || e.key === "1") { e.preventDefault(); flipped ? answer(false) : flip(); }
      else if (e.key === "ArrowRight" || e.key === "2") { e.preventDefault(); flipped ? answer(true) : flip(); }
    };
    document.addEventListener("keydown", keyHandler);
    draw();
  }

  function cleanupKeys() {
    if (keyHandler) document.removeEventListener("keydown", keyHandler);
    keyHandler = null;
  }

  await load();
  home();
  return cleanupKeys;
}
