// 继续上次没做完的题（模考、专项练习、真题、错题复习）：按存档恢复已答的题、标记、每题用时和剩余时间
import { runQuiz, quizDraft } from "../quiz.js";

export async function render(el) {
  const d = quizDraft();
  if (!d) {
    el.innerHTML = `<div class="card empty"><h3>没有没做完的题</h3><p>可能已经交卷或放弃了。</p><a class="btn" href="#/practice">去刷题</a></div>`;
    return () => {};
  }
  return runQuiz(el, {
    title: d.title, ids: d.ids, mode: d.mode, timeLimit: d.timeLimit, resume: d,
    onAgain: () => { location.hash = d.mode === "exam" ? "#/mock" : "#/practice"; },
  });
}
