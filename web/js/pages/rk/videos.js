// 软考 · 视频课：资料文件夹里的视频按文件夹分组、按序号排好，在软件里播放，记住看到哪里、看完的打勾，看的时间记进学习时长
import { apiGet, apiPost, esc, store, toast } from "../../lib.js";

const fmtT = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

export async function render(el, ctx) {
  const data = await apiGet("/api/rk/videos");
  const groups = data.groups || [];
  const all = groups.flatMap((g) => g.items.map((it) => ({ ...it, group: g.title })));
  const state = store.get("rk-video", {}); // {id: {t: 秒, d: 时长, done}}
  let current = all.find((x) => x.id === ctx.parts[1]) || null;
  let watched = 0, lastTick = 0;

  if (!all.length) {
    el.innerHTML = `<div class="page-head"><div><div class="eyebrow">学习</div><h1>视频课</h1>
      <p>还没有整理视频。在资料库里点“整理全部资料”，软件会找出资料文件夹里的视频（只读取，不移动）。</p></div></div>
      <div class="card"><a class="btn primary" href="#/library">去资料库</a></div>`;
    return;
  }

  const save = (v) => {
    if (!current || !v) return;
    const s = state[current.id] || {};
    s.t = Math.floor(v.currentTime); s.d = Math.floor(v.duration || s.d || 0);
    if (s.d && s.t / s.d > 0.92) s.done = 1;
    state[current.id] = s;
    store.set("rk-video", state);
  };
  const logTime = () => {
    const min = Math.floor(watched / 60);
    if (min >= 1) { apiPost("/api/study_log", { module: "教程", minutes: min, source: "视频课" }).catch(() => {}); watched -= min * 60; }
  };

  function itemHTML(it) {
    const s = state[it.id] || {};
    const pct = s.d ? Math.min(100, Math.round((s.t / s.d) * 100)) : 0;
    return `<a class="vid-item ${current?.id === it.id ? "active" : ""} ${s.done ? "done" : ""}" href="#/video/${encodeURIComponent(it.id)}">
      <span class="vid-ck" aria-hidden="true">${s.done ? "✓" : "▶"}</span><span class="vid-n">${esc(it.name)}</span>
      ${pct && !s.done ? `<small class="num">${pct}%</small>` : ""}</a>`;
  }

  const doneN = all.filter((x) => state[x.id]?.done).length;
  el.innerHTML = `
    <div class="page-head"><div><div class="eyebrow">学习</div><h1>视频课</h1>
      <p>${all.length} 讲 · 看完 ${doneN} 讲。播放时记住进度，下次接着看；看的时间算进当天的学习时长。</p></div></div>
    <div class="vid-layout">
      <div class="card vid-player">${current ? `
        <video id="v" controls preload="metadata" src="/api/library/file/${encodeURIComponent(current.id)}"></video>
        <div class="row mt"><b>${esc(current.name)}</b><span class="spacer"></span>
          <span class="small muted">${esc(current.group)}</span>
          <select id="rate" aria-label="播放速度">${[1, 1.25, 1.5, 1.75, 2].map((r) => `<option value="${r}" ${(store.get("rk-video-rate", 1.25) === r) ? "selected" : ""}>${r}×</option>`).join("")}</select>
          <button class="btn sm" id="mark">${state[current.id]?.done ? "标为没看完" : "标为看完"}</button></div>`
        : `<div class="empty"><h3>选一讲开始</h3><p class="small muted">建议先按教程的顺序看基础精讲，再看真题讲解和直播专题。</p></div>`}</div>
      <div class="vid-list card">${groups.map((g) => `<details ${current ? (g.items.some((x) => x.id === current.id) ? "open" : "") : "open"}>
        <summary><b>${esc(g.title)}</b> <small class="muted">${g.items.filter((x) => state[x.id]?.done).length}/${g.items.length}</small></summary>
        ${g.items.map(itemHTML).join("")}</details>`).join("")}</div>
    </div>`;

  const v = el.querySelector("#v");
  if (v) {
    v.playbackRate = store.get("rk-video-rate", 1.25);
    v.addEventListener("loadedmetadata", () => {
      const s = state[current.id];
      if (s?.t && !s.done && s.t < v.duration - 5) { v.currentTime = s.t; toast(`接着上次看到 ${fmtT(s.t)}`); }
    });
    v.addEventListener("timeupdate", () => {
      const now = Date.now();
      if (!v.paused && lastTick) watched += Math.min(2, (now - lastTick) / 1000);
      lastTick = now;
      if (Math.floor(v.currentTime) % 10 === 0) save(v);
    });
    v.addEventListener("pause", () => { lastTick = 0; save(v); logTime(); });
    v.addEventListener("ended", () => {
      save(v); logTime();
      const i = all.findIndex((x) => x.id === current.id);
      if (all[i + 1]) location.hash = `#/video/${encodeURIComponent(all[i + 1].id)}`;
    });
    el.querySelector("#rate").onchange = (e) => { v.playbackRate = +e.target.value; store.set("rk-video-rate", +e.target.value); };
    el.querySelector("#mark").onclick = () => {
      const s = state[current.id] || {};
      s.done = s.done ? 0 : 1; state[current.id] = s; store.set("rk-video", state); render(el, ctx);
    };
  }
  return () => { if (v) { save(v); v.pause(); } logTime(); };
}
