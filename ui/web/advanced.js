/**
 * 高级设置页面逻辑
 */
(function () {
  "use strict";

  // ==================== 调试模式 ====================
  const debugToggle = document.getElementById("debugToggle");
  if (!debugToggle) return;

  async function loadDebugState() {
    try {
      const resp = await fetch("/api/debug");
      const data = await resp.json();
      debugToggle.checked = !!data.enabled;
    } catch (_error) {
      // ignore
    }
  }

  debugToggle.addEventListener("change", async () => {
    const enabled = debugToggle.checked;
    try {
      await fetch("/api/debug", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      });
    } catch (_error) {
      debugToggle.checked = !enabled;
    }
  });

  // ==================== 全局代理 ====================
  const proxyToggle = document.getElementById("proxyToggle");
  const proxyFields = document.getElementById("proxyFields");
  const proxyUrlInput = document.getElementById("proxyUrl");
  const proxyNoProxyInput = document.getElementById("proxyNoProxy");
  const proxySaveBtn = document.getElementById("proxySaveBtn");
  const proxyStatus = document.getElementById("proxyStatus");

  async function loadProxyState() {
    try {
      const resp = await fetch("/api/proxy");
      const data = await resp.json();
      const cfg = data.config || {};
      proxyToggle.checked = !!cfg.enabled;
      proxyFields.style.display = cfg.enabled ? "" : "none";
      if (cfg.url) proxyUrlInput.value = cfg.url;
      if (cfg.noProxy && Array.isArray(cfg.noProxy)) {
        proxyNoProxyInput.value = cfg.noProxy.join(", ");
      }
    } catch (_error) {
      // ignore
    }
  }

  proxyToggle.addEventListener("change", async () => {
    const enabled = proxyToggle.checked;
    proxyFields.style.display = enabled ? "" : "none";
    // 立即保存开关状态
    const noProxyStr = proxyNoProxyInput.value.trim();
    const noProxy = noProxyStr ? noProxyStr.split(/[,，]/).map(function (s) { return s.trim(); }).filter(Boolean) : [];
    try {
      await fetch("/api/proxy", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled: enabled,
          url: proxyUrlInput.value.trim(),
          noProxy: noProxy,
        }),
      });
      proxyStatus.textContent = enabled ? "代理已启用" : "代理已关闭";
      proxyStatus.style.color = enabled ? "var(--ok)" : "var(--ink-soft)";
    } catch (_error) {
      proxyToggle.checked = !enabled;
      proxyFields.style.display = !enabled ? "" : "none";
    }
  });

  proxySaveBtn.addEventListener("click", async () => {
    const enabled = proxyToggle.checked;
    const url = proxyUrlInput.value.trim();
    const noProxyStr = proxyNoProxyInput.value.trim();
    const noProxy = noProxyStr ? noProxyStr.split(/[,，]/).map(function (s) { return s.trim(); }).filter(Boolean) : [];

    if (enabled && !url) {
      proxyStatus.textContent = "请填写代理地址";
      proxyStatus.style.color = "var(--err)";
      return;
    }

    proxySaveBtn.disabled = true;
    proxySaveBtn.textContent = "保存中...";
    try {
      await fetch("/api/proxy", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: enabled, url: url, noProxy: noProxy }),
      });
      proxyStatus.textContent = "已保存";
      proxyStatus.style.color = "var(--ok)";
    } catch (e) {
      proxyStatus.textContent = "保存失败: " + e.message;
      proxyStatus.style.color = "var(--err)";
    } finally {
      proxySaveBtn.disabled = false;
      proxySaveBtn.textContent = "保存";
    }
  });

  // ==================== 初始化 ====================
  loadDebugState();
  loadProxyState();
})();