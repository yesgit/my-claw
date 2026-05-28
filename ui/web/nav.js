/**
 * MyClaw 公用顶部导航栏
 *
 * 用法：在 nav 链接容器上添加 data-nav="auto"，脚本自动生成导航链接。
 *
 * 支持属性：
 *   data-nav="auto"         — 必填，标记要填充的容器
 *   data-nav-active="xxx"   — 可选，强制指定激活项的 href（如 "/settings"）
 *                              不设置时根据当前 URL 自动检测
 *
 * 示例：
 *   <div class="top-nav-links" data-nav="auto"></div>
 *   <div class="top-nav-links" data-nav="auto" data-nav-active="/settings"></div>
 */
(function () {
  var NAV_ITEMS = [
    { label: "控制台", href: "/", exact: true },
    { label: "知识库", href: "/knowledge", exact: true },
    { label: "配置中心", href: "/settings", exact: false }
  ];

  function renderNav(container) {
    var pathname = window.location.pathname;
    var forceActive = container.getAttribute("data-nav-active");
    var testPath = forceActive || pathname;
    var matched = false;

    NAV_ITEMS.forEach(function (item) {
      var a = document.createElement("a");
      a.className = "nav-link";
      a.href = item.href;
      a.textContent = item.label;

      var isMatch = item.exact
        ? testPath === item.href
        : testPath.startsWith(item.href);

      if (!matched && isMatch) {
        a.classList.add("active");
        matched = true;
      }

      container.appendChild(a);
    });
  }

  document.querySelectorAll('[data-nav="auto"]').forEach(renderNav);
})();