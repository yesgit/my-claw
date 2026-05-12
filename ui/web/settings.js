const navModelsBtn = document.getElementById("navModels");
const navMcpBtn = document.getElementById("navMcp");
const settingsFrameEl = document.getElementById("settingsFrame");

const PAGES = {
  models: "/models?embedded=1",
  mcp: "/mcp?embedded=1",
};

function resolveTargetFromHash() {
  const hash = String(window.location.hash || "").replace("#", "").trim().toLowerCase();
  if (hash === "mcp") {
    return "mcp";
  }
  return "models";
}

function renderNav(target) {
  navModelsBtn.classList.toggle("active", target === "models");
  navMcpBtn.classList.toggle("active", target === "mcp");
}

function openTarget(target, pushHash = true) {
  const normalized = target === "mcp" ? "mcp" : "models";
  renderNav(normalized);
  settingsFrameEl.src = PAGES[normalized];
  if (pushHash) {
    window.location.hash = normalized;
  }
}

navModelsBtn.addEventListener("click", () => openTarget("models"));
navMcpBtn.addEventListener("click", () => openTarget("mcp"));
window.addEventListener("hashchange", () => openTarget(resolveTargetFromHash(), false));

openTarget(resolveTargetFromHash(), false);
