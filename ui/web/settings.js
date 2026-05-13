const navModelsBtn = document.getElementById("navModels");
const navMcpBtn = document.getElementById("navMcp");
const navSessionsBtn = document.getElementById("navSessions");
const settingsFrameEl = document.getElementById("settingsFrame");

const PAGES = {
  models: "/models?embedded=1",
  mcp: "/mcp?embedded=1",
  sessions: "/sessions?embedded=1",
};

function resolveTargetFromHash() {
  const hash = String(window.location.hash || "").replace("#", "").trim().toLowerCase();
  if (hash === "sessions") {
    return "sessions";
  }
  if (hash === "mcp") {
    return "mcp";
  }
  return "models";
}

function renderNav(target) {
  navModelsBtn.classList.toggle("active", target === "models");
  navMcpBtn.classList.toggle("active", target === "mcp");
  navSessionsBtn.classList.toggle("active", target === "sessions");
}

function openTarget(target, pushHash = true) {
  const normalized = target === "mcp" || target === "sessions" ? target : "models";
  renderNav(normalized);
  settingsFrameEl.src = PAGES[normalized];
  if (pushHash) {
    window.location.hash = normalized;
  }
}

navModelsBtn.addEventListener("click", () => openTarget("models"));
navMcpBtn.addEventListener("click", () => openTarget("mcp"));
navSessionsBtn.addEventListener("click", () => openTarget("sessions"));
window.addEventListener("hashchange", () => openTarget(resolveTargetFromHash(), false));

openTarget(resolveTargetFromHash(), false);
