/**
 * 高级设置页面逻辑
 */
(function () {
  "use strict";

  const debugToggle = document.getElementById("debugToggle");
  if (!debugToggle) return;

  // 加载当前状态
  async function loadState() {
    try {
      const resp = await fetch("/api/debug");
      const data = await resp.json();
      debugToggle.checked = !!data.enabled;
    } catch (_error) {
      // ignore
    }
  }

  // 切换调试模式
  debugToggle.addEventListener("change", async () => {
    const enabled = debugToggle.checked;
    try {
      await fetch("/api/debug", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      });
    } catch (_error) {
      // 回滚 UI
      debugToggle.checked = !enabled;
    }
  });

  loadState();
})();