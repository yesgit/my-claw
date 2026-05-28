const navModelsBtn = document.getElementById("navModels");
const navMcpBtn = document.getElementById("navMcp");
const navSessionsBtn = document.getElementById("navSessions");
const navExportImportBtn = document.getElementById("navExportImport");
const navQuickPromptsBtn = document.getElementById("navQuickPrompts");
const navAdvancedBtn = document.getElementById("navAdvanced");
const navEmailBtn = document.getElementById("navEmail");
const settingsFrameEl = document.getElementById("settingsFrame");

const PAGES = {
  models: "/models?embedded=1",
  mcp: "/mcp?embedded=1",
  sessions: "/sessions?embedded=1",
  "export-import": "/export-import?embedded=1",
  "quick-prompts": "/quick-prompts?embedded=1",
  advanced: "/advanced?embedded=1",
  email: "/email?embedded=1",
};

function resolveTargetFromHash() {
  const hash = String(window.location.hash || "").replace("#", "").trim().toLowerCase();
  if (hash === "sessions") return "sessions";
  if (hash === "export-import") return "export-import";
  if (hash === "quick-prompts") return "quick-prompts";
  if (hash === "advanced") return "advanced";
  if (hash === "email") return "email";
  if (hash === "mcp") return "mcp";
  return "models";
}

function renderNav(target) {
  navModelsBtn.classList.toggle("active", target === "models");
  navMcpBtn.classList.toggle("active", target === "mcp");
  navSessionsBtn.classList.toggle("active", target === "sessions");
  navExportImportBtn.classList.toggle("active", target === "export-import");
  navQuickPromptsBtn.classList.toggle("active", target === "quick-prompts");
  if (navAdvancedBtn) navAdvancedBtn.classList.toggle("active", target === "advanced");
  if (navEmailBtn) navEmailBtn.classList.toggle("active", target === "email");
}

function openTarget(target, pushHash = true) {
  const validTargets = ["models", "mcp", "sessions", "export-import", "quick-prompts", "advanced", "email"];
  const normalized = validTargets.includes(target) ? target : "models";
  renderNav(normalized);
  settingsFrameEl.src = PAGES[normalized];
  if (pushHash) {
    window.location.hash = normalized;
  }
}

navModelsBtn.addEventListener("click", () => openTarget("models"));
navMcpBtn.addEventListener("click", () => openTarget("mcp"));
navSessionsBtn.addEventListener("click", () => openTarget("sessions"));
navExportImportBtn.addEventListener("click", () => openTarget("export-import"));
navQuickPromptsBtn.addEventListener("click", () => openTarget("quick-prompts"));
if (navAdvancedBtn) navAdvancedBtn.addEventListener("click", () => openTarget("advanced"));
if (navEmailBtn) navEmailBtn.addEventListener("click", () => openTarget("email"));
window.addEventListener("hashchange", () => openTarget(resolveTargetFromHash(), false));

openTarget(resolveTargetFromHash(), false);
