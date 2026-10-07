// 笔记本：自己容易忘的公式、知识点分本子记下来，随时翻看；“遮住自测”时只露标题，点一下才显示内容
import { apiGet, apiPost, esc, mathText, store, toast } from "../lib.js";

export async function render(el) {
  let books = [], items = [];
  let cur = store.get("memo-book", "all"); // "all" | "star" | 本子 id
  let q = "";
  let cover = !!store.get("memo-cover", false);
  let editing = null; // null | "new" | 条目 id
  const shown = new Set(); // 自测时已经翻开的条目

  async function load() {
    ({ books, items } = await apiGet("/api/memo"));
    if (cur !== "all" && cur !== "star" && !books.some((b) => b.id === cur)) cur = "all";
  }

  const bookName = (id) => books.find((b) => b.id === id)?.name || "（笔记本已删除）";
  const countOf = (id) => items.filter((x) => x.book === id).length;

  function visible() {
    let list = cur === "all" ? items : cur === "star" ? items.filter((x) => x.star) : items.filter((x) => x.book === cur);
    if (q) {
      const words = q.split(/\s+/).filter(Boolean);
      list = list.filter((x) => words.every((w) => (x.title + x.content + x.note + x.source).includes(w)));
    }
    return list;
  }

  function editorHTML(it) {
    const book = it?.book ?? (typeof cur === "number" ? cur : store.get("memo-last-book", books[0]?.id));
    return `<div class="card memo-edit">
      <div class="row"><b>${it ? "修改这一条" : "记一条"}</b><span class="spacer"></span>
        <label class="small muted">笔记本 <select id="me-book">${books.map((b) => `<option value="${b.id}" ${b.id === book ? "selected" : ""}>${esc(b.name)}</option>`).join("")}</select></label></div>
      <input id="me-title" placeholder="标题（可选），如：增长量公式、容易混的两个朝代" value="${esc(it?.title || "")}" autocomplete="off">
      <textarea id="me-content" rows="4" placeholder="要记住的内容。公式可以写成 $\\frac{现期-基期}{基期}$ 或 $$a^2+b^2=c^2$$">${esc(it?.content || "")}</textarea>
      <div class="memo-preview" id="me-preview"></div>
      <textarea id="me-note" rows="2" placeholder="自己的理解、口诀、易错点（可选）">${esc(it?.note || "")}</textarea>
      <div class="row"><span class="small muted">Ctrl + Enter 保存</span><span class="spacer"></span>
        <button class="btn sm ghost" id="me-cancel">取消</button><button class="btn sm primary" id="me-save">保存</button></div>
    </div>`;
  }

  function itemHTML(it) {
    const hide = cover && !shown.has(it.id);
    const head = it.title || (it.source ? it.source.split(" · ").pop() : "");
    const src = it.doc
      ? `<a class="small" href="#/library/doc/${encodeURIComponent(it.doc)}?s=${it.seq ?? 0}" title="回到原文">${esc(it.source || "原文")} ›</a>`
      : `<span class="small muted">${esc(it.source || "自己写的")}</span>`;
    return `<div class="memo-item${hide ? " covered" : ""}${it.content.length > 220 ? " long" : ""}" data-id="${it.id}">
      <div class="memo-head">${it.star ? `<span class="memo-star" title="置顶">★</span>` : ""}${head ? `<b>${esc(head)}</b>` : ""}
        ${cur === "all" || cur === "star" ? `<span class="chip">${esc(bookName(it.book))}</span>` : ""}</div>
      <div class="memo-reveal" data-reveal="${it.id}">
        <div class="memo-body">${mathText(it.content)}</div>
        ${it.note ? `<div class="memo-note">✎ ${mathText(it.note)}</div>` : ""}
        ${hide ? `<span class="memo-tip">先想一想，点一下看内容</span>` : ""}
      </div>
      <div class="sc-foot">${src}<span class="spacer"></span>
        <button class="btn sm ghost" data-star="${it.id}" title="${it.star ? "取消置顶" : "置顶，排在最前面"}">${it.star ? "★" : "☆"}</button>
        <button class="btn sm ghost" data-edit="${it.id}">编辑</button>
        <button class="btn sm ghost danger" data-del="${it.id}">删除</button></div>
    </div>`;
  }

  function draw() {
    const list = visible();
    const isBook = typeof cur === "number";
    el.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">笔记本</div><h1>容易忘的，记在笔记本上</h1>
        <p>公式、易错知识点、总记混的常识，分本子记下来随时翻。在资料库里选中文字，工具条上直接点笔记本的名字就记进去了；新建的笔记本会自动出现在工具条上，也会出现在“闪卡记忆”里。</p></div>
        <div class="row"><button class="btn ${cover ? "primary" : ""}" id="cover" title="只露标题，内容先遮住，适合考前过一遍">${cover ? "✓ 遮住自测中" : "遮住自测"}</button>
          <button class="btn" id="newbook2">＋ 新建笔记本</button><button class="btn primary" id="add">＋ 记一条</button></div></div>
      <div class="lib-layout">
        <div class="card lib-side" style="padding:12px 8px">
          <button data-b="all" class="${cur === "all" ? "active" : ""}">全部<small>${items.length}</small></button>
          <button data-b="star" class="${cur === "star" ? "active" : ""}">★ 置顶<small>${items.filter((x) => x.star).length}</small></button>
          <h4>我的笔记本</h4>
          ${books.map((b) => `<button data-b="${b.id}" class="${cur === b.id ? "active" : ""}">${esc(b.name)}<small>${countOf(b.id)}</small></button>`).join("")}
          <button id="newbook" class="memo-addbook">＋ 新建笔记本</button>
        </div>
        <div class="stack" style="gap:14px">
          <div class="card sc-bar">
            <input type="search" id="mq" placeholder="搜标题、内容、笔记" value="${esc(q)}" autocomplete="off">
            ${isBook ? `<button class="btn ghost" id="rename">改名</button><button class="btn ghost danger" id="delbook">删除这个笔记本</button>` : ""}
          </div>
          ${editing === "new" ? editorHTML(null) : ""}
          ${list.length ? `<div class="small muted">${q ? `找到 ${list.length} 条` : `共 ${list.length} 条`}${cover ? " · 点卡片看内容" : ""}</div>` : ""}
          <div class="memo-list">${list.map((it) => (editing === it.id ? editorHTML(it) : itemHTML(it))).join("")}</div>
          ${list.length ? "" : `<div class="card empty"><h3>${q ? "没有找到" : "这里还是空的"}</h3>
            <p>${q ? "换个关键词试试" : "在资料库阅读时选中一段文字，点工具条上的笔记本名字；或者点右上角“记一条”自己写。"}</p></div>`}
        </div>
      </div>`;
    bind();
  }

  function bindEditor() {
    const box = el.querySelector(".memo-edit");
    if (!box) return;
    const content = box.querySelector("#me-content");
    const preview = box.querySelector("#me-preview");
    const paint = () => {
      const t = content.value;
      preview.hidden = !/\$|\\\(|\\\[|⦅/.test(t); // 有公式时才显示预览
      preview.innerHTML = mathText(t);
    };
    content.oninput = paint;
    paint();
    (editing === "new" ? box.querySelector("#me-title") : content).focus();
    const save = async () => {
      const body = {
        book: +box.querySelector("#me-book").value, title: box.querySelector("#me-title").value.trim(),
        content: content.value.trim(), note: box.querySelector("#me-note").value.trim(),
      };
      if (!body.content) { toast("内容还没写"); content.focus(); return; }
      try {
        if (editing === "new") await apiPost("/api/memo", body);
        else await apiPost("/api/memo", { id: editing, ...body });
        store.set("memo-last-book", body.book);
        editing = null;
        await load();
        draw();
        toast("已保存");
      } catch (e) { toast(e.message); }
    };
    box.querySelector("#me-save").onclick = save;
    box.querySelector("#me-cancel").onclick = () => { editing = null; draw(); };
    box.onkeydown = (e) => {
      if (e.key === "Enter" && e.ctrlKey) { e.preventDefault(); save(); }
      if (e.key === "Escape") { editing = null; draw(); }
    };
  }

  function bind() {
    el.querySelectorAll("[data-b]").forEach((b) => (b.onclick = () => {
      cur = /^\d+$/.test(b.dataset.b) ? +b.dataset.b : b.dataset.b;
      store.set("memo-book", cur);
      editing = null;
      draw();
    }));
    el.querySelector("#cover").onclick = () => { cover = !cover; shown.clear(); store.set("memo-cover", cover); draw(); };
    el.querySelector("#add").onclick = () => { editing = "new"; draw(); };
    const mq = el.querySelector("#mq");
    mq.oninput = () => {
      q = mq.value.trim();
      const pos = mq.selectionStart;
      draw();
      const again = el.querySelector("#mq");
      again.focus();
      again.setSelectionRange(pos, pos);
    };

    el.querySelector("#newbook2").onclick = () => el.querySelector("#newbook").click();
    el.querySelector("#newbook").onclick = (e) => {
      const box = document.createElement("input");
      box.placeholder = "笔记本名字，回车创建";
      box.className = "memo-newbook";
      e.currentTarget.replaceWith(box);
      box.focus();
      box.onblur = () => draw();
      box.onkeydown = async (ev) => {
        if (ev.key === "Escape") { draw(); return; }
        if (ev.key !== "Enter" || !box.value.trim()) return;
        box.onblur = null;
        try {
          const { id } = await apiPost("/api/memo/book", { name: box.value.trim() });
          cur = id;
          store.set("memo-book", cur);
          await load();
          draw();
        } catch (err) { toast(err.message); }
      };
    };
    const rename = el.querySelector("#rename");
    if (rename) rename.onclick = () => {
      const box = document.createElement("input");
      box.value = bookName(cur);
      box.className = "memo-newbook";
      box.title = "回车保存，Esc 取消";
      rename.replaceWith(box);
      box.select();
      box.onblur = () => draw();
      box.onkeydown = async (ev) => {
        if (ev.key === "Escape") { draw(); return; }
        if (ev.key !== "Enter" || !box.value.trim()) return;
        box.onblur = null;
        try { await apiPost("/api/memo/book", { id: cur, name: box.value.trim() }); await load(); draw(); } catch (e) { toast(e.message); }
      };
    };
    const delbook = el.querySelector("#delbook");
    if (delbook) delbook.onclick = async () => {
      const n = countOf(cur);
      if (n && !delbook.dataset.armed) {
        delbook.dataset.armed = "1";
        delbook.textContent = `里面 ${n} 条也会删掉，再点一次确认`;
        return;
      }
      await apiPost("/api/memo/book/delete", { id: cur });
      cur = "all";
      store.set("memo-book", cur);
      await load();
      draw();
    };

    el.querySelectorAll("[data-reveal]").forEach((x) => (x.onclick = (e) => {
      if (!cover || e.target.closest("a")) return;
      const id = +x.dataset.reveal;
      shown.has(id) ? shown.delete(id) : shown.add(id);
      const item = x.closest(".memo-item");
      item.classList.toggle("covered", !shown.has(id));
      item.querySelector(".memo-tip")?.remove();
    }));
    el.querySelectorAll("[data-star]").forEach((b) => (b.onclick = async () => {
      const it = items.find((x) => x.id === +b.dataset.star);
      await apiPost("/api/memo", { id: it.id, star: it.star ? 0 : 1 });
      await load();
      draw();
    }));
    el.querySelectorAll("[data-edit]").forEach((b) => (b.onclick = () => { editing = +b.dataset.edit; draw(); }));
    el.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => {
      if (!b.dataset.armed) { b.dataset.armed = "1"; b.textContent = "确定删除？"; return; }
      await apiPost("/api/memo/delete", { id: +b.dataset.del });
      await load();
      draw();
    }));
    bindEditor();
  }

  await load();
  draw();
}
