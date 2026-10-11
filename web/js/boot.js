// 在样式表加载之前就定下界面风格和深浅色，打开时不会先闪一下另一套主题。
// 真正的设置存在学习记录里（lib.js 的 store），app.js 启动后会再套用一次，并把结果抄一份到这里读的 localStorage。
(function () {
  try {
    var d = document.documentElement;
    var skin = localStorage.getItem("gk-skin");
    if (skin === "cabinet" || skin === "porcelain") d.setAttribute("data-skin", skin);
    var theme = localStorage.getItem("gk-theme");
    if (theme === "light" || theme === "dark") d.setAttribute("data-theme", theme);
  } catch (e) { /* 无痕模式等读不了 localStorage：用默认的白瓷星轨、跟随系统 */ }
})();
