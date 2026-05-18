const runBtn = document.getElementById("runBtn");
const timelineEl = document.getElementById("timeline");
const historyListEl = document.getElementById("historyList");
const healthBadgeEl = document.getElementById("healthBadge");
const stepTemplate = document.getElementById("stepTemplate");
const consoleLogEl = document.getElementById("consoleLog");
const providerSelectEl = document.getElementById("providerSelect");
const modelSelectEl = document.getElementById("modelSelect");
const maxStepsEl = document.getElementById("maxSteps");
const modelProfileHintEl = document.getElementById("modelProfileHint");
const currentModelTagEl = document.getElementById("currentModelTag");
const recentModelSwitchesEl = document.getElementById("recentModelSwitches");
const mcpConfigHintEl = document.getElementById("mcpConfigHint");
const approvalQueueEl = document.getElementById("approvalQueue");
const sessionSelectEl = document.getElementById("sessionSelect");
const sessionHintEl = document.getElementById("sessionHint");

// 暴露当前会话 ID 给权限 Tab 等外部模块
window._getActiveSessionId = () => String(sessionSelectEl?.value || "").trim() || null;
const sessionMetaEl = document.getElementById("sessionMeta");
const sessionMetaInlineEl = document.getElementById("sessionMetaInline");
const configChipModelEl = document.getElementById("configChipModel");
const configChipModelLabelEl = document.getElementById("configChipModelLabel");
const createSessionBtn = document.getElementById("createSessionBtn");
const createSessionFromScheduleBtn = document.getElementById("createSessionFromScheduleBtn");
const refreshSessionsBtn = document.getElementById("refreshSessionsBtn");
const refreshSchedulesBtn = document.getElementById("refreshSchedulesBtn");
const railTabSessionsEl = document.getElementById("railTabSessions");
const railTabSchedulesEl = document.getElementById("railTabSchedules");
const railPaneSessionsEl = document.getElementById("railPaneSessions");
const railPaneSchedulesEl = document.getElementById("railPaneSchedules");
const goalEl = document.getElementById("goal");
const debugTabButtons = Array.from(document.querySelectorAll(".debug-tab-btn"));
const scheduleHintEl = document.getElementById("scheduleHint");
const scheduleListEl = document.getElementById("scheduleList");
const runtimeSessionHintEl = document.getElementById("runtimeSessionHint");
const runtimeSessionListEl = document.getElementById("runtimeSessionList");
const attachBtn = document.getElementById("attachBtn");
const fileInput = document.getElementById("fileInput");
const attachmentChipsEl = document.getElementById("attachmentChips");
const composerArea = document.getElementById("composerArea");

// Popover elements
const sessionPopoverEl = document.getElementById("sessionPopover");
const modelPopoverEl = document.getElementById("modelPopover");
const sessionSelectPopoverEl = document.getElementById("sessionSelectPopover");
const providerSelectPopoverEl = document.getElementById("providerSelectPopover");
const modelSelectPopoverEl = document.getElementById("modelSelectPopover");
const currentModelTagPopoverEl = document.getElementById("currentModelTagPopover");

const HISTORY_KEY = "myclaw-agent-history-v1";
const PROVIDER_KEY = "myclaw-selected-provider";
const MODEL_KEY = "myclaw-selected-model";
const MODEL_SWITCHES_KEY = "myclaw-model-switches-v1";
const SESSION_KEY = "myclaw-selected-session";
const ACTIVE_TAB_KEY = "myclaw-active-tab";
const ACTIVE_RAIL_TAB_KEY = "myclaw-active-rail-tab";
const ACTIVE_RUN_KEY = "myclaw-active-run-id";
const PENDING_APPROVALS_BY_SESSION_KEY = "myclaw-pending-approvals-by-session-v1";
const PENDING_APPROVALS_KEY = "myclaw-pending-approvals-v1";
const QUICK_PROMPTS_KEY = "myclaw-quick-prompts-v1";

let historyItems = loadHistory();
let activeRunId = loadActiveRunId() || (historyItems.length ? historyItems[0].id : null);
let activeStepKey = null;
let isRunning = false;
let currentRunStartMs = 0;
let liveRun = null;
let currentRunServerId = null;
let pendingApprovals = loadPendingApprovals();
let modelConfig = { defaultProviderId: "", defaultModelId: "", providers: [] };
let mcpConfigState = { defaultConfigPath: "", servers: [] };
let recentModelSwitches = loadRecentModelSwitches();
let sessions = [];
let sessionRunItems = [];
let sessionSchedules = [];
let scheduleRunsById = {};
let runtimeSessions = [];
let currentRunTaskId = null;
let activeTab = "chat";
let activeRailTab = "sessions";
let consoleSnapshotRunId = null;
let currentAbortController = null;

// ---- 文件附件管理 ----
let pendingFiles = []; // { file: File, id: number }

function addPendingFiles(fileList) {
  for (const file of fileList) {
    if (file.size > 20 * 1024 * 1024) {
      appendConsoleLine("WARN", `文件 ${file.name} 超过 20MB，已跳过`, "err");
      continue;
    }
    pendingFiles.push({ file, id: Date.now() + Math.random() });
  }
  renderAttachmentChips();
}

function removePendingFile(id) {
  pendingFiles = pendingFiles.filter((f) => f.id !== id);
  renderAttachmentChips();
}

function clearPendingFiles() {
  pendingFiles = [];
  renderAttachmentChips();
}

function formatFileSize(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

function renderAttachmentChips() {
  if (!attachmentChipsEl) return;
  attachmentChipsEl.innerHTML = "";
  for (const item of pendingFiles) {
    const chip = document.createElement("div");
    chip.className = "attachment-chip";
    chip.innerHTML = `
      <span class="attachment-chip-name" title="${escapeHtml(item.file.name)}">${escapeHtml(item.file.name)}</span>
      <span class="attachment-chip-size">${formatFileSize(item.file.size)}</span>
      <button type="button" class="attachment-chip-remove" title="移除">&times;</button>
    `;
    chip.querySelector(".attachment-chip-remove").addEventListener("click", () => removePendingFile(item.id));
    attachmentChipsEl.appendChild(chip);
  }
}

if (attachBtn) {
  attachBtn.addEventListener("click", () => fileInput?.click());
}
if (fileInput) {
  fileInput.addEventListener("change", () => {
    if (fileInput.files.length) addPendingFiles(fileInput.files);
    fileInput.value = "";
  });
}
if (composerArea) {
  composerArea.addEventListener("dragover", (e) => { e.preventDefault(); composerArea.classList.add("drag-over"); });
  composerArea.addEventListener("dragleave", () => composerArea.classList.remove("drag-over"));
  composerArea.addEventListener("drop", (e) => {
    e.preventDefault();
    composerArea.classList.remove("drag-over");
    if (e.dataTransfer.files.length) addPendingFiles(e.dataTransfer.files);
  });
  composerArea.addEventListener("paste", (e) => {
    const files = e.clipboardData?.files;
    if (files && files.length) {
      e.preventDefault();
      addPendingFiles(files);
    }
  });
}

function switchTab(tabName) {
  if (activeTab === tabName) return;
  activeTab = tabName;
  saveActiveTab();
  renderTabs();
  if (tabName === "perm" && typeof window._permTabRefresh === "function") {
    window._permTabRefresh();
  }
}

function saveActiveTab() {
  localStorage.setItem(ACTIVE_TAB_KEY, activeTab);
}

function loadActiveTab() {
  const saved = localStorage.getItem(ACTIVE_TAB_KEY);
  if (saved && ["chat", "console", "perm"].includes(saved)) {
    activeTab = saved;
  }
}

function saveActiveRailTab() {
  localStorage.setItem(ACTIVE_RAIL_TAB_KEY, activeRailTab);
}

function loadActiveRailTab() {
  const saved = localStorage.getItem(ACTIVE_RAIL_TAB_KEY);
  if (saved && ["sessions", "schedules"].includes(saved)) {
    activeRailTab = saved;
  }
}

function switchRailTab(tabName) {
  if (!tabName || !["sessions", "schedules"].includes(tabName)) {
    return;
  }
  if (activeRailTab === tabName) {
    return;
  }
  activeRailTab = tabName;
  saveActiveRailTab();
  renderRailTabs();

  // Auto-select first item in the target tab
  if (tabName === "sessions") {
    const firstSession = sessions
      .filter((s) => String(s.session_type || "normal") !== "schedule-runtime")
      .sort((a, b) => {
        if (a.pinned !== b.pinned) return b.pinned ? 1 : -1;
        return String(b.updated_at || "").localeCompare(String(a.updated_at || ""));
      })[0];
    if (firstSession && sessionSelectEl.value !== firstSession.id) {
      sessionSelectEl.value = firstSession.id;
      localStorage.setItem(SESSION_KEY, firstSession.id);
      updateSessionHint();
      loadSessionTasks(firstSession.id)
        .then(() => syncPendingApprovalsForSession(firstSession.id))
        .then(() => renderAll())
        .catch(() => renderAll());
    }
  } else if (tabName === "schedules") {
    const firstRuntime = sessions
      .filter((s) => String(s.session_type || "") === "schedule-runtime")
      .sort((a, b) => {
        if (a.pinned !== b.pinned) return b.pinned ? 1 : -1;
        return String(b.updated_at || "").localeCompare(String(a.updated_at || ""));
      })[0];
    if (firstRuntime && sessionSelectEl.value !== firstRuntime.id) {
      sessionSelectEl.value = firstRuntime.id;
      localStorage.setItem(SESSION_KEY, firstRuntime.id);
      updateSessionHint();
      loadSessionTasks(firstRuntime.id)
        .then(() => loadSessionSchedules(firstRuntime.id))
        .then(() => syncPendingApprovalsForSession(firstRuntime.id))
        .then(() => renderAll())
        .catch(() => renderAll());
    }
  }
}

function renderRailTabs() {
  if (!railTabSessionsEl || !railTabSchedulesEl || !railPaneSessionsEl || !railPaneSchedulesEl) {
    return;
  }
  const isSessions = activeRailTab === "sessions";

  railTabSessionsEl.classList.toggle("active", isSessions);
  railTabSchedulesEl.classList.toggle("active", !isSessions);
  railTabSessionsEl.setAttribute("aria-selected", isSessions ? "true" : "false");
  railTabSchedulesEl.setAttribute("aria-selected", isSessions ? "false" : "true");

  railPaneSessionsEl.hidden = !isSessions;
  railPaneSchedulesEl.hidden = isSessions;
}

function saveActiveRunId() {
  if (activeRunId) {
    localStorage.setItem(ACTIVE_RUN_KEY, activeRunId);
  }
}

function loadActiveRunId() {
  return localStorage.getItem(ACTIVE_RUN_KEY);
}

function renderTabs() {
  debugTabButtons.forEach((btn) => {
    btn.classList.remove("active");
  });
  const activeBtn = debugTabButtons.find((btn) => btn.dataset.tab === activeTab);
  if (activeBtn) {
    activeBtn.classList.add("active");
  }

  const allPanes = document.querySelectorAll(".debug-tab-pane");
  allPanes.forEach((pane) => {
    pane.classList.remove("active");
  });
  const activePane = document.getElementById(`${activeTab}Tab`);
  if (activePane) {
    activePane.classList.add("active");
  }
}

function getValue(id) {
  return document.getElementById(id).value.trim();
}

function setValue(id, value) {
  document.getElementById(id).value = value;
}

function formatIsoLike(value) {
  if (!value) {
    return "-";
  }
  try {
    return new Date(value).toLocaleString("zh-CN", { hour12: false });
  } catch (_error) {
    return String(value);
  }
}

function setRunning(running) {
  isRunning = running;
  runBtn.disabled = false; // 不再禁用，运行时变为"停止"按钮
  runBtn.textContent = running ? "停止" : "发送";
  runBtn.classList.toggle("is-stop", running);
  if (running) {
    currentRunStartMs = Date.now();
  }
}

function stopCurrentRun() {
  if (currentAbortController) {
    currentAbortController.abort();
    currentAbortController = null;
  }
  if (liveRun) {
    liveRun.result.status = "stopped";
    liveRun.result.finalAnswer = liveRun.result.finalAnswer || "任务已被用户手动停止";
    liveRun.result.durationMs = Math.max(0, Date.now() - currentRunStartMs);
  }
  appendConsoleLine("STOP", "任务已被用户手动停止", "err");
  setRunning(false);
  if (liveRun) {
    pushRun(liveRun.goal, liveRun.result);
  }
  if (sessionSelectEl.value) {
    loadSessions(sessionSelectEl.value).catch(() => null);
    loadSessionTasks(sessionSelectEl.value).catch(() => null);
  }
  currentRunTaskId = null;
  currentRunServerId = null;
  renderAll();
}

function beginLiveRun(goal) {
  liveRun = {
    id: `live-${Date.now()}`,
    goal,
    createdAt: new Date().toISOString(),
    result: {
      status: "running",
      finalAnswer: "",
      durationMs: 0,
      progressText: "任务已提交，等待开始...",
      steps: [],
      events: [],
    },
  };
  activeRunId = liveRun.id;
  activeStepKey = null;
  saveActiveRunId();
}

function updateLiveProgress(text) {
  if (!liveRun) {
    return;
  }
  liveRun.result.status = "running";
  liveRun.result.progressText = String(text || "智能体思考中...");
}

function appendConsoleLine(tag, text, tone = "dim") {
  const line = document.createElement("div");
  line.className = `console-line ${tone}`;
  const tagEl = document.createElement("span");
  tagEl.className = "console-tag";
  tagEl.textContent = tag;
  const bodyEl = document.createElement("span");
  bodyEl.textContent = text;
  line.appendChild(tagEl);
  line.appendChild(bodyEl);
  consoleLogEl.appendChild(line);
  consoleLogEl.scrollTop = consoleLogEl.scrollHeight;
}

function appendConsoleBlock(tag, title, lines, tone = "dim") {
  const block = document.createElement("div");
  block.className = `console-block ${tone}`;

  const details = document.createElement("details");
  details.className = "console-details";
  details.open = true;

  const head = document.createElement("summary");
  head.className = "console-block-head";

  const tagEl = document.createElement("span");
  tagEl.className = "console-tag";
  tagEl.textContent = tag;

  const titleEl = document.createElement("span");
  titleEl.className = "console-block-title";
  titleEl.textContent = title;

  const tsEl = document.createElement("span");
  tsEl.className = "console-ts";
  tsEl.textContent = new Date().toLocaleTimeString("zh-CN", { hour12: false });

  head.appendChild(tagEl);
  head.appendChild(titleEl);
  head.appendChild(tsEl);

  const body = document.createElement("pre");
  body.className = "console-block-body";
  body.textContent = lines.join("\n");

  details.appendChild(head);
  details.appendChild(body);
  block.appendChild(details);
  consoleLogEl.appendChild(block);
  consoleLogEl.scrollTop = consoleLogEl.scrollHeight;
}

function clearConsole() {
  consoleLogEl.innerHTML = "";
}

function getStepOperationPairs(step) {
  if (!step) {
    return [];
  }

  if (step.operation && step.observation) {
    return [{ operation: step.operation, observation: step.observation }];
  }

  const operations = Array.isArray(step.operations) ? step.operations : [];
  const observations = Array.isArray(step.observations) ? step.observations : [];
  const pairs = [];
  for (let i = 0; i < operations.length; i += 1) {
    pairs.push({
      operation: operations[i] || {},
      observation: observations[i] || {},
    });
  }
  return pairs;
}

function inferPolicyDecision(observation) {
  if (!observation || typeof observation !== "object") {
    return "unknown";
  }
  if (observation.error === "rejected_by_policy_guard") {
    return "rejected";
  }
  return "allowed_or_not_required";
}

function renderConsoleFromEvents(events) {
  for (const event of events) {
    switch (event.type) {
      case "session_renamed":
        if (event.session_id && event.name) {
          appendConsoleLine("SESSION", `会话已重命名：${event.name}`, "ok");
        }
        break;
      case "run_boot":
        appendConsoleBlock("BOOT", "开始任务", [`goal: ${event.goal}`], "dim");
        break;
      case "approval_required":
        appendConsoleBlock(
          "GATE",
          "等待人工审批",
          [
            `运行ID: ${event.run_id || "-"}`,
            `审批ID: ${event.approval_id || "-"}`,
            `操作: ${(event.operation || {}).tool || "-"}.${(event.operation || {}).action || "-"}`,
          ],
          "dim",
        );
        break;
      case "approval_timeout":
        appendConsoleBlock(
          "GATE",
          "审批超时，默认拒绝",
          [`审批ID: ${event.approval_id || "-"}`, `决策: ${event.default_decision || "n"}`],
          "err",
        );
        break;
      case "run_start":
        appendConsoleBlock("RUN", "任务已接收", [`goal: ${event.goal}`], "dim");
        break;
      case "step_start":
        appendConsoleBlock("STEP", `Step ${event.step}`, ["state: start"], "dim");
        break;
      case "llm_pending":
        appendConsoleBlock("LLM", `Step ${event.step} 等待模型响应`, ["state: pending"], "dim");
        break;
      case "llm_response":
        appendConsoleBlock("LLM", `Step ${event.step} 模型响应`, ["state: received", `bytes: ${String(event.content || "").length}`], "dim");
        break;
      case "action_start":
        appendConsoleBlock("CMD", toShellCommand(event.operation), summarizeOperation(event.operation), "dim");
        break;
      case "approval":
        appendConsoleBlock(
          "GATE",
          event.approved ? "Policy Guard: approved" : "Policy Guard: rejected",
          [
            `step: ${event.step}`,
            `tool_call_id: ${event.tool_call_id || "-"}`,
            `decision: ${event.approved ? "allow" : "deny"}`,
            `operation: ${event.operation?.tool || "-"}.${event.operation?.action || "-"}`,
          ],
          event.approved ? "ok" : "err",
        );
        break;
      case "action_result": {
        const statusTone = event.observation && event.observation.ok ? "ok" : "err";
        appendConsoleBlock(
          "OBS",
          statusTone === "ok" ? "Tool result" : "Tool error",
          summarizeObservation(event.observation),
          statusTone,
        );
        break;
      }
      case "step_complete":
        appendConsoleBlock(
          "STEP",
          `Step ${event.step} completed`,
          [
            `records: ${Array.isArray(event.step_record?.operations) ? event.step_record.operations.length : 1}`,
            `tool_call_id: ${event.step_record?.tool_call_id || (Array.isArray(event.step_record?.tool_call_ids) ? event.step_record.tool_call_ids.join(",") : "-")}`,
          ],
          "ok",
        );
        break;
      case "run_complete":
        appendConsoleBlock("DONE", "任务完成", [`status: ${event.status}`, `final_answer: ${event.final_answer}`], "ok");
        break;
      case "run_error":
        appendConsoleBlock("DONE", "任务失败", [`error: ${event.message}`], "err");
        break;
      default:
        appendConsoleLine("INFO", summarizeObject(event), "dim");
        break;
    }
  }
}

function renderConsoleFromRun(runItem, clearBefore = true) {
  if (clearBefore) {
    clearConsole();
  }
  if (!runItem) {
    return;
  }

  const status = runItem.result?.status || "unknown";
  const tone = status === "completed" ? "ok" : status === "error" ? "err" : "dim";

  // 展示用户提问
  if (runItem.goal) {
    const userLine = document.createElement("div");
    userLine.className = "console-user-question";
    userLine.innerHTML = `<span class='console-user-label'>用户</span><span class='console-user-text'>${escapeHtml(runItem.goal)}</span>`;
    consoleLogEl.appendChild(userLine);
  }

  // 展示 events 或 steps，带缩进和虚线
  const events = Array.isArray(runItem.result?.events) ? runItem.result.events : [];
  if (events.length) {
    renderConsoleFromEventsIndented(events);
    return;
  }

  const steps = Array.isArray(runItem.result?.steps) ? runItem.result.steps : [];
  if (!steps.length) {
    appendConsoleLine("HISTORY", "该任务没有保存步骤数据", "dim");
  }

  for (const step of steps) {
    const pairs = getStepOperationPairs(step);
    if (!pairs.length) {
      appendConsoleBlockIndented("STEP", `Step ${step.step || "-"}`, ["no operation records"], "dim");
      continue;
    }

    pairs.forEach((pair, idx) => {
      const operationLines = summarizeOperation(pair.operation);
      const observationLines = summarizeObservation(pair.observation);
      const policyDecision = inferPolicyDecision(pair.observation);
      const statusTone = pair.observation && pair.observation.ok ? "ok" : pair.observation?.error ? "err" : "dim";
      appendConsoleBlockIndented(
        "STEP",
        `Step ${step.step || "-"}${pairs.length > 1 ? ` #${idx + 1}` : ""}`,
        [
          ...operationLines,
          `policy: ${policyDecision}`,
          ...observationLines,
        ],
        statusTone,
      );
    });
  }

  if (runItem.result?.finalAnswer) {
    appendConsoleBlockIndented("DONE", "历史最终回答", [`final_answer: ${runItem.result.finalAnswer}`], tone);
  }
}

function renderConsoleForSession() {
  clearConsole();

  const selectedSessionId = String(sessionSelectEl.value || "").trim();
  if (!selectedSessionId) {
    return;
  }

  const runs = sessionRunItems
    .slice()
    .sort((a, b) => {
      const aTs = Date.parse(String(a.createdAt || "")) || 0;
      const bTs = Date.parse(String(b.createdAt || "")) || 0;
      return aTs - bTs;
    });

  if (!runs.length) {
    return;
  }

  runs.forEach((runItem, idx) => {
    if (idx > 0) {
      appendConsoleLine("SESSION", "--------------------------------", "dim");
    }
    renderConsoleFromRun(runItem, false);
  });
}

// 新增：带缩进和虚线的 events 渲染
function renderConsoleFromEventsIndented(events) {
  for (const event of events) {
    appendConsoleBlockIndented("EVENT", event.type || "event", [summarizeObject(event)], "dim");
  }
}

// 新增：带缩进和虚线的块
function appendConsoleBlockIndented(tag, title, lines, tone = "dim") {
  const block = document.createElement("div");
  block.className = `console-block console-block-indented ${tone}`;

  // 虚线缩进
  const indent = document.createElement("div");
  indent.className = "console-indent-dashed";
  block.appendChild(indent);

  const details = document.createElement("details");
  details.className = "console-details";
  details.open = true;

  const head = document.createElement("summary");
  head.className = "console-block-head";

  const tagEl = document.createElement("span");
  tagEl.className = "console-tag";
  tagEl.textContent = tag;

  const titleEl = document.createElement("span");
  titleEl.className = "console-block-title";
  titleEl.textContent = title;

  const tsEl = document.createElement("span");
  tsEl.className = "console-ts";
  tsEl.textContent = new Date().toLocaleTimeString("zh-CN", { hour12: false });

  head.appendChild(tagEl);
  head.appendChild(titleEl);
  head.appendChild(tsEl);

  const body = document.createElement("pre");
  body.className = "console-block-body";
  body.textContent = lines.join("\n");

  details.appendChild(head);
  details.appendChild(body);
  block.appendChild(details);
  consoleLogEl.appendChild(block);
  consoleLogEl.scrollTop = consoleLogEl.scrollHeight;
}

function syncConsoleForActiveRun() {
  const selectedSessionId = String(sessionSelectEl.value || "").trim();
  if (!selectedSessionId) {
    clearConsole();
    consoleSnapshotRunId = null;
    return;
  }

  const runItem = getCurrentRun();
  const runId = String(runItem?.id || "");
  const isLiveRunning = !!liveRun && runItem && liveRun.id === runId && isRunning;
  if (isLiveRunning) {
    consoleSnapshotRunId = null;
    return;
  }

  const sessionSnapshotId = `${selectedSessionId}:${sessionRunItems.length}:${sessionRunItems[sessionRunItems.length - 1]?.id || ""}`;
  if (consoleSnapshotRunId === sessionSnapshotId) {
    return;
  }

  renderConsoleForSession();
  consoleSnapshotRunId = sessionSnapshotId;
}

function summarizeObject(value) {
  if (value == null) {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  try {
    return JSON.stringify(value);
  } catch (_error) {
    return String(value);
  }
}

function formatKeyValueLines(entries) {
  return entries
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .map(([key, value]) => `${key}: ${value}`);
}

function summarizeOperation(operation) {
  if (!operation) {
    return [];
  }
  return formatKeyValueLines([
    ["工具", operation.tool],
    ["动作", operation.action],
    ["资源", operation.resource],
    ["风险等级", formatRiskLevelLabel(operation.risk)],
    ["参数", summarizeObject(operation.params)],
  ]);
}

function toShellCommand(operation) {
  if (!operation) {
    return "$ unknown";
  }
  const resource = operation.resource ? ` \"${operation.resource}\"` : "";
  return `$ ${operation.tool}.${operation.action}${resource}`;
}

function summarizeObservation(observation) {
  if (!observation) {
    return [];
  }
  const lines = formatKeyValueLines([
    ["ok", observation.ok],
    ["error", observation.error],
    ["tool_call_id", observation.tool_call_id],
  ]);
  if (observation.result) {
    lines.push(`result: ${summarizeObject(observation.result)}`);
  }
  if (observation.batch) {
    lines.push(`batch: ${summarizeObject(observation.batch)}`);
  }
  return lines;
}

function loadHistory() {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch (_error) {
    return [];
  }
}

function loadRecentModelSwitches() {
  try {
    const raw = localStorage.getItem(MODEL_SWITCHES_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch (_error) {
    return [];
  }
}

function loadPendingApprovals() {
  try {
    const groupedRaw = localStorage.getItem(PENDING_APPROVALS_BY_SESSION_KEY);
    if (groupedRaw) {
      const grouped = JSON.parse(groupedRaw);
      if (!grouped || typeof grouped !== "object") {
        return [];
      }
      const merged = [];
      for (const [sessionId, approvals] of Object.entries(grouped)) {
        if (!Array.isArray(approvals)) {
          continue;
        }
        for (const item of approvals) {
          if (!item || typeof item !== "object") {
            continue;
          }
          if (!item.run_id || !item.approval_id) {
            continue;
          }
          merged.push({
            ...item,
            session_id: String(item.session_id || sessionId || getSessionIdFromRunId(item.run_id) || ""),
          });
        }
      }
      return merged;
    }

    // 兼容旧版本：从扁平数组读取并补齐 session_id。
    const raw = localStorage.getItem(PENDING_APPROVALS_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed
      .filter((item) => item && typeof item === "object" && item.run_id && item.approval_id)
      .map((item) => ({
        ...item,
        session_id: String(item.session_id || getSessionIdFromRunId(item.run_id) || ""),
      }));
  } catch (_error) {
    return [];
  }
}

function savePendingApprovals() {
  const grouped = {};
  for (const item of pendingApprovals) {
    const sessionId = String(item.session_id || getSessionIdFromRunId(item.run_id) || "");
    const key = sessionId || "_unknown";
    if (!grouped[key]) {
      grouped[key] = [];
    }
    grouped[key].push({
      ...item,
      session_id: sessionId,
    });
  }
  localStorage.setItem(PENDING_APPROVALS_BY_SESSION_KEY, JSON.stringify(grouped));
  // 旧 key 写空，避免旧逻辑重复读取到历史脏数据。
  localStorage.setItem(PENDING_APPROVALS_KEY, JSON.stringify([]));
}

async function syncPendingApprovalsForSession(sessionId) {
  const normalized = String(sessionId || "").trim();
  if (!normalized) {
    return;
  }

  try {
    const resp = await fetch(`/api/sessions/${encodeURIComponent(normalized)}/approvals/pending`);
    if (!resp.ok) {
      return;
    }
    const data = await resp.json();
    const approvals = Array.isArray(data.approvals) ? data.approvals : [];
    const aliveKeys = new Set(
      approvals
        .filter((item) => item && item.run_id && item.approval_id)
        .map((item) => `${item.run_id}:${item.approval_id}`),
    );

    pendingApprovals = pendingApprovals.filter((item) => {
      const ownerSessionId = String(item.session_id || getSessionIdFromRunId(item.run_id) || "");
      if (ownerSessionId !== normalized) {
        return true;
      }
      return aliveKeys.has(`${item.run_id || "-"}:${item.approval_id || "-"}`);
    });
    savePendingApprovals();
    renderApprovalQueue();
  } catch (_error) {
    // 对账失败不阻断主流程，下次切换会话时会再次对账。
  }
}

function saveRecentModelSwitches() {
  localStorage.setItem(MODEL_SWITCHES_KEY, JSON.stringify(recentModelSwitches.slice(0, 8)));
}

function saveHistory() {
  localStorage.setItem(HISTORY_KEY, JSON.stringify(historyItems.slice(0, 20)));
}

function toRunTitle(goal) {
  if (!goal) {
    return "未命名任务";
  }
  return goal.length > 26 ? `${goal.slice(0, 26)}...` : goal;
}

function getRunById(runId) {
  if (liveRun && liveRun.id === runId) {
    return liveRun;
  }
  const sessionItem = sessionRunItems.find((item) => item.id === runId);
  if (sessionItem) {
    return sessionItem;
  }
  return historyItems.find((item) => item.id === runId) || null;
}

function renderHealth(status, text) {
  healthBadgeEl.className = `health ${status}`;
  healthBadgeEl.textContent = text;
}

async function checkHealth() {
  renderHealth("checking", "连接检测中");
  try {
    const resp = await fetch("/api/health");
    if (!resp.ok) {
      throw new Error("status not ok");
    }
    renderHealth("ok", "后端在线");
  } catch (_error) {
    renderHealth("err", "后端离线");
  }
}

async function loadModelConfig() {
  try {
    const resp = await fetch("/api/model-config");
    if (!resp.ok) {
      throw new Error("load model config failed");
    }
    modelConfig = await resp.json();
  } catch (_error) {
    modelConfig = { defaultProviderId: "", defaultModelId: "", providers: [] };
  }
  renderProviderAndModelSelectors();
}

async function loadMcpConfig() {
  try {
    const resp = await fetch("/api/mcp-config");
    if (!resp.ok) {
      throw new Error("load mcp config failed");
    }
    mcpConfigState = await resp.json();
  } catch (_error) {
    mcpConfigState = { defaultConfigPath: "", servers: [] };
  }

  const serverCount = Array.isArray(mcpConfigState.servers) ? mcpConfigState.servers.length : 0;
  const path = String(mcpConfigState.defaultConfigPath || "").trim();
  if (serverCount > 0) {
    mcpConfigHintEl.textContent = `当前使用内嵌 MCP servers：${serverCount} 个`;
  } else {
    mcpConfigHintEl.textContent = path ? `当前兜底配置：${path}` : "未配置 MCP server（将不加载 MCP tools）";
  }
}

function toSessionRunItem(task) {
  return {
    id: `task:${task.id}`,
    sourceTaskId: task.id,
    goal: task.goal,
    createdAt: task.created_at,
    result: {
      status: task.status,
      finalAnswer: task.final_answer || "",
      durationMs: task.duration_ms || 0,
      steps: Array.isArray(task.steps) ? task.steps : [],
      events: Array.isArray(task.events) ? task.events : [],
    },
  };
}

async function loadSessionTasks(sessionId) {
  if (!sessionId) {
    sessionRunItems = [];
    activeRunId = null;
    activeStepKey = null;
    saveActiveRunId();
    renderAll();
    return;
  }

  try {
    const resp = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/tasks?limit=50`);
    if (!resp.ok) {
      throw new Error("load tasks failed");
    }
    const data = await resp.json();
    const tasks = Array.isArray(data.tasks) ? data.tasks : [];
    sessionRunItems = tasks.map(toSessionRunItem);
    activeRunId = sessionRunItems.length ? sessionRunItems[sessionRunItems.length - 1].id : null;
    activeStepKey = null;
    saveActiveRunId();
  } catch (_error) {
    sessionRunItems = [];
    activeRunId = null;
    activeStepKey = null;
    saveActiveRunId();
  }
}

async function loadSessionSchedules(sessionId) {
  if (!sessionId) {
    sessionSchedules = [];
    scheduleRunsById = {};
    return;
  }
  try {
    const resp = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/schedules?includeDisabled=true`);
    if (!resp.ok) {
      throw new Error("load schedules failed");
    }
    const data = await resp.json();
    sessionSchedules = Array.isArray(data.schedules) ? data.schedules : [];
  } catch (_error) {
    sessionSchedules = [];
  }

  const aliveIds = new Set(sessionSchedules.map((item) => String(item.id || "")));
  const nextCache = {};
  for (const [key, value] of Object.entries(scheduleRunsById)) {
    if (aliveIds.has(key)) {
      nextCache[key] = value;
    }
  }
  scheduleRunsById = nextCache;
}

async function loadRuntimeSessions() {
  runtimeSessions = sessions.filter((item) => String(item.session_type || "") === "schedule-runtime");
}

function renderRuntimeSessions() {
  if (!runtimeSessionHintEl || !runtimeSessionListEl) {
    return;
  }

  if (!runtimeSessions.length) {
    runtimeSessionHintEl.textContent = "暂无定时任务会话，点击新建创建一个。";
    runtimeSessionListEl.innerHTML = "";
    return;
  }

  runtimeSessionHintEl.textContent = "";
  runtimeSessionListEl.innerHTML = "";

  const sorted = runtimeSessions
    .slice()
    .sort((a, b) => {
      const aPinned = a.pinned ? 1 : 0;
      const bPinned = b.pinned ? 1 : 0;
      if (aPinned !== bPinned) {
        return bPinned - aPinned;
      }
      return String(b.updated_at || "").localeCompare(String(a.updated_at || ""));
    })
    .slice(0, 30);

  const pinnedSessions = sorted.filter((item) => item.pinned);
  const normalSessions = sorted.filter((item) => !item.pinned);

  const appendRuntimeCard = (item) => {
    const isActiveSession = item.id === sessionSelectEl.value;
    const card = document.createElement("div");
    // 同时挂载 session-card 兼容类，避免样式类名漂移导致卡片样式丢失
    card.className = "history-item session-card";
    if (isActiveSession) card.classList.add("active");
    if (item.pinned) card.classList.add("is-pinned");
    card.setAttribute("role", "button");
    card.tabIndex = 0;

    const normalizedName = String(item.name || "").trim() === "定时任务执行会话"
      ? "定时任务会话"
      : String(item.name || "").trim();
    const sessionName = escapeHtml(normalizedName || "定时任务会话");
    const taskCount = Number(item.task_count || 0);
    const metaParts = [];
    if (taskCount > 0) {
      metaParts.push(`任务 ${escapeHtml(String(taskCount))}`);
    }
    metaParts.push(`更新于 ${escapeHtml(formatIsoLike(item.updated_at))}`);
    card.innerHTML = `
      <div class="session-item-top">
        <button type="button" class="session-name-btn" aria-label="重命名运行会话">${sessionName}</button>
        <div class="session-actions">
          <button type="button" class="ghost-btn mini session-pin-btn ${item.pinned ? "is-active" : ""}" aria-label="${item.pinned ? "取消置顶" : "置顶会话"}" title="${item.pinned ? "取消置顶" : "置顶会话"}">📌</button>
          <button type="button" class="ghost-btn mini session-archive-btn" aria-label="归档会话" title="归档会话">📥</button>
          <button type="button" class="ghost-btn mini session-delete-btn" aria-label="删除会话" title="删除会话">🗑️</button>
        </div>
      </div>
      <div class="session-meta-sub">${metaParts.join(" · ")}</div>
    `;

    const selectRuntimeSession = () => {
      sessionSelectEl.value = item.id;
      localStorage.setItem(SESSION_KEY, item.id);
      updateSessionHint();
      Promise.all([
        loadSessionTasks(item.id),
        loadSessionSchedules(item.id),
      ])
        .then(() => syncPendingApprovalsForSession(item.id))
        .then(() => renderAll())
        .catch(() => renderAll());
    };

    card.addEventListener("click", selectRuntimeSession);
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectRuntimeSession();
      }
    });

    const nameBtn = card.querySelector(".session-name-btn");
    const pinBtn = card.querySelector(".session-pin-btn");
    const archiveBtn = card.querySelector(".session-archive-btn");
    const deleteBtn = card.querySelector(".session-delete-btn");

    if (pinBtn) {
      pinBtn.addEventListener("click", async (event) => {
        event.stopPropagation();
        pinBtn.disabled = true;
        try {
          await updateSessionStateById(item.id, { pinned: !item.pinned });
          await loadSessions(sessionSelectEl.value || item.id);
          runtimeSessionHintEl.textContent = item.pinned ? "已取消置顶" : "已置顶";
        } catch (_error) {
          pinBtn.disabled = false;
          runtimeSessionHintEl.textContent = "置顶状态更新失败";
        }
      });
    }

    if (archiveBtn) {
      let archiveConfirmTimer = null;
      const resetArchiveButton = () => {
        archiveBtn.dataset.confirming = "0";
        archiveBtn.classList.remove("is-pending");
        archiveBtn.textContent = "📥";
        archiveBtn.title = "归档会话";
      };
      archiveBtn.addEventListener("click", async (event) => {
        event.stopPropagation();
        if (archiveBtn.dataset.confirming !== "1") {
          archiveBtn.dataset.confirming = "1";
          archiveBtn.classList.add("is-pending");
          archiveBtn.textContent = "✓";
          archiveBtn.title = "再次点击确认归档";
          if (archiveConfirmTimer) {
            clearTimeout(archiveConfirmTimer);
          }
          archiveConfirmTimer = setTimeout(resetArchiveButton, 3000);
          return;
        }
        clearTimeout(archiveConfirmTimer);
        archiveConfirmTimer = null;
        archiveBtn.disabled = true;
        archiveBtn.textContent = "...";
        try {
          await updateSessionStateById(item.id, { archived: true });
          if (sessionSelectEl.value === item.id) {
            localStorage.removeItem(SESSION_KEY);
            sessionSelectEl.value = "";
            sessionRunItems = [];
            activeRunId = null;
            activeStepKey = null;
            saveActiveRunId();
          }
          await loadSessions(sessionSelectEl.value);
          runtimeSessionHintEl.textContent = "会话已归档，可到设置页恢复";
        } catch (_error) {
          archiveBtn.disabled = false;
          resetArchiveButton();
          runtimeSessionHintEl.textContent = "会话归档失败";
        }
      });
    }

    if (deleteBtn) {
      let deleteConfirmTimer = null;
      const resetDeleteButton = () => {
        deleteBtn.dataset.confirming = "0";
        deleteBtn.classList.remove("is-pending");
        deleteBtn.textContent = "🗑️";
        deleteBtn.title = "删除会话";
      };
      deleteBtn.addEventListener("click", async (event) => {
        event.stopPropagation();
        if (deleteBtn.dataset.confirming !== "1") {
          deleteBtn.dataset.confirming = "1";
          deleteBtn.classList.add("is-pending");
          deleteBtn.textContent = "✓";
          deleteBtn.title = "再次点击确认删除";
          deleteConfirmTimer = setTimeout(resetDeleteButton, 3000);
          return;
        }
        clearTimeout(deleteConfirmTimer);
        deleteConfirmTimer = null;
        deleteBtn.disabled = true;
        try {
          await deleteSessionById(item.id);
          if (sessionSelectEl.value === item.id) {
            localStorage.removeItem(SESSION_KEY);
            sessionSelectEl.value = "";
            sessionRunItems = [];
            activeRunId = null;
            activeStepKey = null;
            saveActiveRunId();
          }
          await loadSessions(sessionSelectEl.value);
          runtimeSessionHintEl.textContent = "运行会话已删除";
        } catch (_error) {
          deleteBtn.disabled = false;
          resetDeleteButton();
          runtimeSessionHintEl.textContent = "删除失败";
        }
      });
    }

    if (nameBtn) {
      nameBtn.addEventListener("click", (event) => event.stopPropagation());
      nameBtn.addEventListener("dblclick", (event) => {
        event.stopPropagation();
        event.preventDefault();
        if (nameBtn.dataset.editing === "1") return;
        nameBtn.dataset.editing = "1";

        const currentName = String(item.name || "").trim();
        const input = document.createElement("input");
        input.type = "text";
        input.className = "session-name-inline-input";
        input.value = currentName;
        input.maxLength = 40;
        nameBtn.hidden = true;
        nameBtn.insertAdjacentElement("afterend", input);

        let finished = false;
        const finishEdit = async (commit) => {
          if (finished) return;
          finished = true;
          const nextName = String(input.value || "").trim();
          input.remove();
          nameBtn.hidden = false;
          nameBtn.dataset.editing = "0";
          if (!commit || !nextName || nextName === currentName) return;
          try {
            await renameSessionById(item.id, nextName);
            await loadSessions(sessionSelectEl.value || item.id);
            runtimeSessionHintEl.textContent = "名称已更新";
          } catch (_error) {
            runtimeSessionHintEl.textContent = "重命名失败";
          }
        };

        input.addEventListener("keydown", (keyEvent) => {
          keyEvent.stopPropagation();
          if (keyEvent.key === "Enter") { keyEvent.preventDefault(); void finishEdit(true); }
          if (keyEvent.key === "Escape") { keyEvent.preventDefault(); void finishEdit(false); }
        });
        input.addEventListener("blur", () => void finishEdit(true));
        input.focus();
        input.select();
      });
    }

    runtimeSessionListEl.appendChild(card);
  };

  const appendGroupTitle = (title) => {
    const groupTitleEl = document.createElement("div");
    groupTitleEl.className = "session-group-title";
    groupTitleEl.textContent = title;
    runtimeSessionListEl.appendChild(groupTitleEl);
  };

  if (pinnedSessions.length) {
    appendGroupTitle("置顶");
    for (const item of pinnedSessions) {
      appendRuntimeCard(item);
    }
  }

  if (normalSessions.length) {
    appendGroupTitle("其他");
    for (const item of normalSessions) {
      appendRuntimeCard(item);
    }
  }
}

function scheduleStatusText(item) {
  if (!item) return "-";
  if (item.running) return "执行中";
  if (!item.enabled) return "已停用";
  if (item.last_status === "error") return "上次失败";
  if (item.last_status === "completed") return "上次成功";
  return "待执行";
}

async function updateScheduleById(sessionId, scheduleId, payload) {
  const resp = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/schedules/${encodeURIComponent(scheduleId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: "更新定时任务失败" }));
    throw new Error(err.detail || "更新定时任务失败");
  }
}

async function deleteScheduleById(sessionId, scheduleId) {
  const resp = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/schedules/${encodeURIComponent(scheduleId)}`, {
    method: "DELETE",
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: "删除定时任务失败" }));
    throw new Error(err.detail || "删除定时任务失败");
  }
}

async function runScheduleNowById(sessionId, scheduleId) {
  const resp = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/schedules/${encodeURIComponent(scheduleId)}/run-now`, {
    method: "POST",
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: "触发执行失败" }));
    throw new Error(err.detail || "触发执行失败");
  }
}

async function loadScheduleRuns(sessionId, scheduleId, forceReload = false) {
  const key = String(scheduleId || "");
  if (!forceReload && Array.isArray(scheduleRunsById[key])) {
    return scheduleRunsById[key];
  }

  const resp = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/schedules/${encodeURIComponent(scheduleId)}/runs?limit=10`);
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: "加载执行记录失败" }));
    throw new Error(err.detail || "加载执行记录失败");
  }

  const data = await resp.json();
  const rows = Array.isArray(data.runs) ? data.runs : [];
  scheduleRunsById[key] = rows;
  return rows;
}

async function createScheduleByPayload(sessionId, payload) {
  const resp = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/schedules`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: "新增定时任务失败" }));
    throw new Error(err.detail || "新增定时任务失败");
  }
  const data = await resp.json();
  return data.schedule;
}

function parseScheduleCreateFromGoal(goal) {
  const raw = String(goal || "").trim();
  if (!raw) {
    return null;
  }
  if (!/(创建|新建).*(定时任务|计划任务)|(定时任务|计划任务).*(创建|新建)/.test(raw)) {
    return null;
  }

  const nameMatch = raw.match(/名称\s*[:：=]\s*([^\n，,]+)/i);
  const intervalMatch = raw.match(/(?:间隔|interval)\s*[:：=]?\s*(\d{1,6})\s*(?:秒|s|sec|secs)?/i) || raw.match(/每\s*(\d{1,6})\s*秒/i);
  const promptMatch = raw.match(/(?:提示词|prompt|内容)\s*[:：=]\s*([\s\S]+)/i);

  let name = nameMatch ? String(nameMatch[1]).trim() : "";
  const intervalSeconds = intervalMatch ? Number(intervalMatch[1]) : 300;
  let prompt = promptMatch ? String(promptMatch[1]).trim() : "";

  if (!prompt) {
    const lines = raw
      .split(/\n+/)
      .map((item) => item.trim())
      .filter(Boolean)
      .filter((line) => !/^(创建|新建).*(定时任务|计划任务)/.test(line))
      .filter((line) => !/^名称\s*[:：=]/i.test(line))
      .filter((line) => !/^(间隔|interval)\s*[:：=]?/i.test(line))
      .filter((line) => !/^每\s*\d+\s*秒/.test(line));
    prompt = lines.join("\n").trim();
  }

  if (!name) {
    name = `定时任务 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`;
  }

  if (!prompt) {
    return null;
  }

  if (!Number.isFinite(intervalSeconds) || intervalSeconds < 30 || intervalSeconds > 86400) {
    throw new Error("定时任务间隔必须在 30 到 86400 秒之间");
  }

  return {
    name,
    prompt,
    intervalSeconds,
    enabled: true,
  };
}

async function tryHandleScheduleCreateByChat(goalText) {
  let payload = null;
  try {
    payload = parseScheduleCreateFromGoal(goalText);
  } catch (error) {
    throw error;
  }
  if (!payload) {
    return false;
  }

  const sessionId = await ensureSessionIdForRun();
  localStorage.setItem(SESSION_KEY, sessionId);
  updateSessionHint();

  const created = await createScheduleByPayload(sessionId, payload);
  await loadSessionSchedules(sessionId);
  renderAll();

  pushRun(goalText, {
    status: "completed",
    finalAnswer: `已创建定时任务：${created?.name || payload.name}（间隔 ${created?.interval_seconds || payload.intervalSeconds} 秒）`,
    durationMs: 0,
    steps: [],
    events: [],
  });
  if (scheduleHintEl) {
    scheduleHintEl.textContent = "已通过问答创建定时任务。";
  }
  // 轮询检测后端异步 LLM 重命名
  pollSessionNameUpdate(sessionId);
  return true;
}

/**
 * 轮询检测会话名称是否被后端异步更新，名称变化后刷新 UI。
 * @param {string} sessionId - 要监测的会话 ID
 * @param {number} [interval=1500] - 轮询间隔 ms
 * @param {number} [maxAttempts=6] - 最大轮询次数
 */
function pollSessionNameUpdate(sessionId, interval = 1500, maxAttempts = 6) {
  const currentName = String(getSelectedSession()?.name || "").trim();
  let attempts = 0;

  const timer = setInterval(async () => {
    attempts += 1;
    try {
      const resp = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}`);
      if (!resp.ok) { clearInterval(timer); return; }
      const data = await resp.json();
      const newName = String(data?.session?.name || "").trim();
      if (newName && newName !== currentName) {
        clearInterval(timer);
        await loadSessions(sessionId);
      }
    } catch (_error) {
      // 忽略网络错误，继续轮询
    }
    if (attempts >= maxAttempts) {
      clearInterval(timer);
    }
  }, interval);
}

function renderSchedulePanel() {
  if (!scheduleListEl || !scheduleHintEl) {
    return;
  }

  const sessionId = String(sessionSelectEl.value || "").trim();
  scheduleListEl.innerHTML = "";
  railPaneSchedulesEl?.classList.remove("has-schedules");
  if (!sessionId) {
    scheduleHintEl.textContent = "";
    return;
  }

  scheduleHintEl.textContent = "";

  if (!sessionSchedules.length) {
    return;
  }

  railPaneSchedulesEl?.classList.add("has-schedules");

  for (const item of sessionSchedules) {
    const card = document.createElement("article");
    card.className = "schedule-item";
    card.innerHTML = `
      <div class="schedule-item-header">
        <h4 class="schedule-title">${escapeHtml(item.name || "未命名任务")}</h4>
        <span class="schedule-status">${escapeHtml(scheduleStatusText(item))}</span>
      </div>
      <p class="schedule-meta">间隔 ${escapeHtml(String(item.interval_seconds || 0))} 秒 · 下次 ${escapeHtml(formatIsoLike(item.next_run_at))}</p>
      <input type="text" class="schedule-name-input" value="${escapeHtml(item.name || "")}" maxlength="40" />
      <textarea class="schedule-prompt-input" rows="2">${escapeHtml(item.prompt || "")}</textarea>
      <div class="schedule-item-row">
        <input type="number" class="schedule-interval-input" min="30" max="86400" value="${escapeHtml(String(item.interval_seconds || 300))}" />
        <label class="schedule-toggle"><input type="checkbox" class="schedule-enabled-input" ${item.enabled ? "checked" : ""} />启用</label>
      </div>
      <div class="schedule-actions">
        <button type="button" class="ghost-btn schedule-save-btn">保存</button>
        <button type="button" class="ghost-btn schedule-runs-btn">记录</button>
        <button type="button" class="ghost-btn schedule-run-btn">立即执行</button>
        <button type="button" class="ghost-btn schedule-delete-btn">删除</button>
      </div>
      <div class="schedule-runs" hidden></div>
    `;

    const saveBtn = card.querySelector(".schedule-save-btn");
    const runsBtn = card.querySelector(".schedule-runs-btn");
    const runBtnLocal = card.querySelector(".schedule-run-btn");
    const deleteBtn = card.querySelector(".schedule-delete-btn");
    const runsEl = card.querySelector(".schedule-runs");
    const nameInput = card.querySelector(".schedule-name-input");
    const promptInput = card.querySelector(".schedule-prompt-input");
    const intervalInput = card.querySelector(".schedule-interval-input");
    const enabledInput = card.querySelector(".schedule-enabled-input");

    saveBtn?.addEventListener("click", async () => {
      const name = String(nameInput?.value || "").trim();
      const prompt = String(promptInput?.value || "").trim();
      const intervalSeconds = Number(String(intervalInput?.value || "0").trim() || "0");
      const enabled = !!enabledInput?.checked;
      if (!name || !prompt || !Number.isFinite(intervalSeconds) || intervalSeconds < 30 || intervalSeconds > 86400) {
        scheduleHintEl.textContent = "保存失败：请检查名称、提示词和间隔范围（30-86400）。";
        return;
      }
      saveBtn.disabled = true;
      try {
        await updateScheduleById(sessionId, item.id, {
          name,
          prompt,
          intervalSeconds,
          enabled,
        });
        await loadSessionSchedules(sessionId);
        await loadSessions(sessionId);
        scheduleHintEl.textContent = "定时任务已保存。";
        renderSchedulePanel();
        // 轮询检测后端异步 LLM 重命名
        pollSessionNameUpdate(sessionId);
      } catch (error) {
        scheduleHintEl.textContent = `保存失败：${error.message}`;
      } finally {
        saveBtn.disabled = false;
      }
    });

    runBtnLocal?.addEventListener("click", async () => {
      runBtnLocal.disabled = true;
      try {
        await runScheduleNowById(sessionId, item.id);
        scheduleRunsById[String(item.id)] = [];
        scheduleHintEl.textContent = "已触发执行。";
        await loadSessionSchedules(sessionId);
        renderSchedulePanel();
      } catch (error) {
        scheduleHintEl.textContent = `触发失败：${error.message}`;
      } finally {
        runBtnLocal.disabled = false;
      }
    });

    runsBtn?.addEventListener("click", async () => {
      if (!runsEl) {
        return;
      }

      if (!runsEl.hidden) {
        runsEl.hidden = true;
        runsBtn.textContent = "记录";
        return;
      }

      runsEl.hidden = false;
      runsBtn.textContent = "收起";
      runsEl.innerHTML = "<div class='schedule-run-row'>加载中...</div>";

      try {
        const rows = await loadScheduleRuns(sessionId, item.id, true);
        if (!rows.length) {
          runsEl.innerHTML = "<div class='schedule-run-row'>暂无执行记录</div>";
          return;
        }

        runsEl.innerHTML = rows
          .map((row) => {
            const triggerText = row.trigger_type === "manual" ? "手动" : "自动";
            const statusText = row.status || "-";
            const taskText = row.task_id ? ` · 任务 ${escapeHtml(String(row.task_id))}` : "";
            const errorText = row.error ? `<div class='schedule-run-error'>${escapeHtml(String(row.error))}</div>` : "";
            return `<div class='schedule-run-row'>
              <div>${escapeHtml(triggerText)} · ${escapeHtml(statusText)} · ${escapeHtml(formatIsoLike(row.started_at))}${taskText}</div>
              ${errorText}
            </div>`;
          })
          .join("");
      } catch (error) {
        runsEl.innerHTML = `<div class='schedule-run-row'>${escapeHtml(`加载失败：${error.message}`)}</div>`;
      }
    });

    deleteBtn?.addEventListener("click", async () => {
      deleteBtn.disabled = true;
      try {
        await deleteScheduleById(sessionId, item.id);
        await loadSessionSchedules(sessionId);
        await loadSessions(sessionId);
        scheduleHintEl.textContent = "定时任务已删除。";
        renderSchedulePanel();
        // 轮询检测后端异步 LLM 重命名
        pollSessionNameUpdate(sessionId);
      } catch (error) {
        scheduleHintEl.textContent = `删除失败：${error.message}`;
        deleteBtn.disabled = false;
      }
    });

    scheduleListEl.appendChild(card);
  }
}

function updateSessionHint() {
  const selected = getSelectedSession();
  if (!selected) {
    sessionHintEl.textContent = "可直接发送问题，系统会自动创建会话。";
    sessionMetaEl.textContent = "当前会话: -";
    sessionMetaInlineEl.textContent = "当前会话: -";
    renderConfigCapsules();
    return;
  }
  sessionHintEl.textContent = `当前会话: ${selected.name} · 任务数 ${selected.task_count || 0}`;
  sessionMetaEl.textContent = `会话名: ${selected.name} · 更新于: ${formatIsoLike(selected.updated_at)} · 创建于: ${formatIsoLike(selected.created_at)}`;
  sessionMetaInlineEl.textContent = `${selected.name} · ${selected.task_count || 0} 条任务 · 更新于 ${formatIsoLike(selected.updated_at)}`;
  renderConfigCapsules();
}

function getSelectedSession() {
  const selectedId = String(sessionSelectEl.value || "").trim();
  if (!selectedId) {
    return null;
  }
  return sessions.find((item) => item.id === selectedId) || null;
}

function renderConfigCapsules() {
  const selectedId = sessionSelectEl.value;
  const selectedSession = sessions.find((item) => item.id === selectedId);
  const selectedModel = getSelectedProviderAndModel();

  if (configChipModelLabelEl) {
    configChipModelLabelEl.textContent = selectedModel ? `模型: ${selectedModel.model.name}` : "模型: -";
  }
}

function renderSessionSelector(preferredId = "") {
  sessionSelectEl.innerHTML = "";
  if (sessionSelectPopoverEl) {
    sessionSelectPopoverEl.innerHTML = "";
  }
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "请选择会话";
  sessionSelectEl.appendChild(placeholder);
  if (sessionSelectPopoverEl) {
    sessionSelectPopoverEl.appendChild(placeholder.cloneNode(true));
  }

  for (const session of sessions) {
    const option = document.createElement("option");
    option.value = session.id;
    const pinPrefix = session.pinned ? "[置顶] " : "";
    option.textContent = `${pinPrefix}${session.name}`;
    sessionSelectEl.appendChild(option);
    if (sessionSelectPopoverEl) {
      sessionSelectPopoverEl.appendChild(option.cloneNode(true));
    }
  }

  const remembered = localStorage.getItem(SESSION_KEY) || "";
  const wantedId = preferredId || remembered;
  const exists = sessions.some((item) => item.id === wantedId);
  sessionSelectEl.value = exists ? wantedId : "";
  if (sessionSelectEl.value) {
    localStorage.setItem(SESSION_KEY, sessionSelectEl.value);
    if (sessionSelectPopoverEl) {
      sessionSelectPopoverEl.value = sessionSelectEl.value;
    }
  } else {
    localStorage.removeItem(SESSION_KEY);
    if (sessionSelectPopoverEl) {
      sessionSelectPopoverEl.value = "";
    }
  }
  updateSessionHint();
}

async function loadSessions(preferredId = "") {
  try {
    const resp = await fetch("/api/sessions?limit=200&includeRuntime=true");
    if (!resp.ok) {
      throw new Error("load sessions failed");
    }
    const data = await resp.json();
    sessions = Array.isArray(data.sessions) ? data.sessions : [];
  } catch (_error) {
    sessions = [];
  }
  renderSessionSelector(preferredId);
  await loadSessionTasks(sessionSelectEl.value);
  await loadSessionSchedules(sessionSelectEl.value);
  await loadRuntimeSessions();
  await syncPendingApprovalsForSession(sessionSelectEl.value);
  renderAll();
}

function collectSessionConfig() {
  const payload = collectPayload();
  return {
    providerId: payload.providerId,
    modelId: payload.modelId,
    maxSteps: payload.maxSteps,
    mcpConfig: payload.mcpConfig,
    jsonMode: payload.jsonMode,
  };
}

async function createSession(preferredName = "", seedGoal = "", options = {}) {
  const name = String(preferredName || "").trim();
  const sessionType = String(options.sessionType || "normal").trim() || "normal";
  const resp = await fetch("/api/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name,
      seedGoal: String(seedGoal || "").trim(),
      sessionType,
      config: collectSessionConfig(),
    }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: "创建会话失败" }));
    throw new Error(err.detail || "创建会话失败");
  }
  const data = await resp.json();
  const created = data.session;
  await loadSessions(created.id);
  sessionSelectEl.value = created.id;
  localStorage.setItem(SESSION_KEY, created.id);
  updateSessionHint();
  await loadSessionTasks(sessionSelectEl.value);
  await loadSessionSchedules(sessionSelectEl.value);
  renderAll();
  return created.id;
}

async function deleteSessionById(sessionId) {
  const resp = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: "删除会话失败" }));
    throw new Error(err.detail || "删除会话失败");
  }
}

async function renameSessionById(sessionId, name) {
  const normalized = String(name || "").trim();
  if (!normalized) {
    throw new Error("会话名称不能为空");
  }

  const resp = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/name`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: normalized }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: "重命名会话失败" }));
    throw new Error(err.detail || "重命名会话失败");
  }

  const data = await resp.json();
  return data.session;
}

async function updateSessionStateById(sessionId, payload) {
  const resp = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/state`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: "更新会话状态失败" }));
    throw new Error(err.detail || "更新会话状态失败");
  }
  const data = await resp.json();
  return data.session;
}

async function ensureSessionIdForRun() {
  const selected = sessionSelectEl.value;
  if (selected) {
    return selected;
  }
  return createSession("", getValue("goal"));
}

function renderProviderAndModelSelectors() {
  // Update main selects
  providerSelectEl.innerHTML = "";
  modelSelectEl.innerHTML = "";
  
  // Update popover selects
  if (providerSelectPopoverEl) providerSelectPopoverEl.innerHTML = "";
  if (modelSelectPopoverEl) modelSelectPopoverEl.innerHTML = "";
  
  const providers = Array.isArray(modelConfig.providers) ? modelConfig.providers : [];
  if (!providers.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "暂无模型配置，请先去模型配置页添加";
    providerSelectEl.appendChild(option);
    if (providerSelectPopoverEl) providerSelectPopoverEl.appendChild(option.cloneNode(true));
    
    modelSelectEl.innerHTML = "";
    if (modelSelectPopoverEl) modelSelectPopoverEl.innerHTML = "";
    
    modelProfileHintEl.textContent = "未找到可用模型。";
    currentModelTagEl.textContent = "当前模型: -";
    if (currentModelTagPopoverEl) currentModelTagPopoverEl.textContent = "当前模型: -";
    return;
  }

  for (const provider of providers) {
    const option = document.createElement("option");
    option.value = provider.id;
    option.textContent = provider.name;
    providerSelectEl.appendChild(option);
    if (providerSelectPopoverEl) providerSelectPopoverEl.appendChild(option.cloneNode(true));
  }

  const rememberedProvider = localStorage.getItem(PROVIDER_KEY);
  const providerIds = new Set(providers.map((item) => item.id));
  const selectedProviderId = providerIds.has(rememberedProvider)
    ? rememberedProvider
    : providerIds.has(modelConfig.defaultProviderId)
      ? modelConfig.defaultProviderId
      : providers[0].id;

  providerSelectEl.value = selectedProviderId;
  if (providerSelectPopoverEl) providerSelectPopoverEl.value = selectedProviderId;
  localStorage.setItem(PROVIDER_KEY, selectedProviderId);
  renderModelSelectorForProvider(selectedProviderId);
  updateModelProfileHint();
}

function renderModelSelectorForProvider(providerId) {
  modelSelectEl.innerHTML = "";
  if (modelSelectPopoverEl) modelSelectPopoverEl.innerHTML = "";
  
  const provider = (modelConfig.providers || []).find((item) => item.id === providerId);
  if (!provider || !Array.isArray(provider.models) || !provider.models.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "该 provider 暂无可用模型";
    modelSelectEl.appendChild(option);
    if (modelSelectPopoverEl) modelSelectPopoverEl.appendChild(option.cloneNode(true));
    localStorage.setItem(MODEL_KEY, "");
    return;
  }

  for (const model of provider.models) {
    const option = document.createElement("option");
    option.value = model.id;
    option.textContent = `${model.flash ? "⚡ " : ""}${model.name} (${model.model})`;
    modelSelectEl.appendChild(option);
    if (modelSelectPopoverEl) modelSelectPopoverEl.appendChild(option.cloneNode(true));
  }

  const rememberedModel = localStorage.getItem(MODEL_KEY);
  const modelIds = new Set(provider.models.map((item) => item.id));
  const selectedModelId = modelIds.has(rememberedModel)
    ? rememberedModel
    : provider.id === modelConfig.defaultProviderId && modelIds.has(modelConfig.defaultModelId)
      ? modelConfig.defaultModelId
      : provider.models[0].id;
  modelSelectEl.value = selectedModelId;
  if (modelSelectPopoverEl) modelSelectPopoverEl.value = selectedModelId;
  localStorage.setItem(MODEL_KEY, selectedModelId);
}

function updateModelProfileHint() {
  const selected = getSelectedProviderAndModel();
  if (!selected) {
    modelProfileHintEl.textContent = "请先在模型配置页添加模型。";
    currentModelTagEl.textContent = "当前模型: -";
    if (currentModelTagPopoverEl) currentModelTagPopoverEl.textContent = "当前模型: -";
    renderRecentModelSwitches();
    renderConfigCapsules();
    return;
  }
  modelProfileHintEl.textContent = `${selected.provider.baseUrl} · timeout=${selected.provider.timeout}s · ${selected.provider.jsonMode ? "JSON" : "TEXT"}`;
  currentModelTagEl.textContent = `当前模型: ${selected.provider.name} / ${selected.model.name} (${selected.model.model})`;
  if (currentModelTagPopoverEl) currentModelTagPopoverEl.textContent = `当前模型: ${selected.provider.name} / ${selected.model.name} (${selected.model.model})`;
  renderRecentModelSwitches();
  renderConfigCapsules();
}

function getSelectedProviderAndModel() {
  const providerId = providerSelectEl.value;
  const modelId = modelSelectEl.value;
  const provider = (modelConfig.providers || []).find((item) => item.id === providerId);
  if (!provider) {
    return null;
  }
  const model = (provider.models || []).find((item) => item.id === modelId);
  if (!model) {
    return null;
  }
  return { provider, model };
}

function pushModelSwitch(selection) {
  if (!selection) {
    return;
  }
  const latest = recentModelSwitches[0];
  const switchKey = `${selection.provider.id}::${selection.model.id}`;
  if (latest && latest.key === switchKey) {
    return;
  }
  recentModelSwitches = [
    {
      key: switchKey,
      providerName: selection.provider.name,
      modelName: selection.model.name,
      modelValue: selection.model.model,
      at: new Date().toLocaleTimeString("zh-CN", { hour12: false }),
    },
    ...recentModelSwitches,
  ].slice(0, 8);
  saveRecentModelSwitches();
}

function renderRecentModelSwitches() {
  recentModelSwitchesEl.innerHTML = "";
  if (!recentModelSwitches.length) {
    recentModelSwitchesEl.innerHTML = "<div class='switch-item'>暂无切换记录</div>";
    return;
  }
  for (const item of recentModelSwitches) {
    const div = document.createElement("div");
    div.className = "switch-item";
    div.textContent = `${item.at} · ${item.providerName} / ${item.modelName} (${item.modelValue})`;
    recentModelSwitchesEl.appendChild(div);
  }
}

function getCurrentRun() {
  return liveRun || getRunById(activeRunId);
}

function stepKey(step) {
  return String(step.step);
}

function getActiveStep(runItem) {
  if (!runItem || !Array.isArray(runItem.result.steps) || !runItem.result.steps.length) {
    return null;
  }
  return runItem.result.steps.find((step) => stepKey(step) === activeStepKey) || runItem.result.steps[0];
}

function getToolCallLabelFromStep(step) {
  if (!step) {
    return "-";
  }
  if (step.tool_call_id) {
    return step.tool_call_id;
  }
  if (Array.isArray(step.tool_call_ids) && step.tool_call_ids.length) {
    return step.tool_call_ids.join(",");
  }
  return "-";
}

function normalizeInspectorData(step) {
  if (!step) {
    return {
      operation: {},
      observation: {},
      metaText: "请选择一条步骤查看详情",
      empty: true,
    };
  }

  if (step.operation && step.observation) {
    const toolCallLabel = step.tool_call_id ? ` · tool_call_id=${step.tool_call_id}` : "";
    return {
      operation: step.operation,
      observation: step.observation,
      metaText: `Step ${step.step}${toolCallLabel}`,
      empty: false,
    };
  }

  const firstOperation = Array.isArray(step.operations) ? step.operations[0] || {} : {};
  const firstObservation = Array.isArray(step.observations) ? step.observations[0] || {} : {};
  const ids = Array.isArray(step.tool_call_ids) && step.tool_call_ids.length ? ` · ids=${step.tool_call_ids.join(",")}` : "";
  return {
    operation: firstOperation,
    observation: {
      batch: step.observations || [],
      first: firstObservation,
    },
    metaText: `Step ${step.step} · 批量${ids}`,
    empty: false,
  };
}

function renderInspector(step) {
  void step;
}

function getSessionIdFromRunId(runId) {
  const normalized = String(runId || "");
  const match = normalized.match(/^session-(.+?)-task-/);
  return match ? match[1] : "";
}

function getVisiblePendingApprovals() {
  const selectedSessionId = String(sessionSelectEl.value || "").trim();
  if (!selectedSessionId) {
    return [];
  }
  return pendingApprovals.filter(
    (item) => String(item.session_id || getSessionIdFromRunId(item.run_id) || "") === selectedSessionId,
  );
}

function renderTimeline(runItem) {
  timelineEl.innerHTML = "";
  timelineEl.classList.toggle(
    "is-runtime-session",
    String(getSelectedSession()?.session_type || "normal") === "schedule-runtime",
  );
  const sessionId = sessionSelectEl.value;
  const conversationItems = [];

  // 优先显示正在运行的 liveRun，然后显示历史消息
  if (runItem) {
    conversationItems.push(runItem);
  }
  
  if (sessionId && runItem) {
    // 如果 runItem 来自 sessionRunItems，只添加其他项，避免重复
    const runItemId = runItem.id;
    conversationItems.push(
      ...sessionRunItems
        .slice()
        .filter((item) => item.id !== runItemId)
        .sort((a, b) => String(a.createdAt || "").localeCompare(String(b.createdAt || "")))
    );
  } else if (sessionId) {
    conversationItems.push(...sessionRunItems.slice().sort((a, b) => String(a.createdAt || "").localeCompare(String(b.createdAt || ""))));
  }

  // 归属过滤：liveRun 与后端 task 绑定后，只保留一条会话消息链
  const linkedTaskId = String(currentRunTaskId || "").trim();
  const hasLinkedLiveRun = !!liveRun && !!linkedTaskId;
  const ownedItems = hasLinkedLiveRun
    ? conversationItems.filter((item) => {
        if (item.id === liveRun.id) {
          return true;
        }
        const itemTaskId = String(item.sourceTaskId || "").trim();
        const itemRunId = String(item.id || "").trim();
        return itemTaskId !== linkedTaskId && itemRunId !== `task:${linkedTaskId}`;
      })
    : conversationItems;

  // 去重：确保不会显示重复的消息
  const seenIds = new Set();
  const uniqueItems = [];
  for (const item of ownedItems) {
    if (!seenIds.has(item.id)) {
      uniqueItems.push(item);
      seenIds.add(item.id);
    }
  }

  if (!uniqueItems.length) {
    timelineEl.innerHTML = "<div class='chat-empty'>暂无对话。先在底部输入消息并发送。</div>";
    renderInspector(null);
    return;
  }

  const sortedItems = uniqueItems
    .map((item, idx) => ({ item, idx }))
    .sort((left, right) => {
      const leftTs = Date.parse(String(left.item.createdAt || "")) || 0;
      const rightTs = Date.parse(String(right.item.createdAt || "")) || 0;
      if (leftTs !== rightTs) {
        return leftTs - rightTs;
      }

      const leftIsLive = String(left.item.id || "").startsWith("live-") ? 1 : 0;
      const rightIsLive = String(right.item.id || "").startsWith("live-") ? 1 : 0;
      if (leftIsLive !== rightIsLive) {
        return leftIsLive - rightIsLive;
      }

      return left.idx - right.idx;
    })
    .map((entry) => entry.item);

  for (const item of sortedItems) {
    const isActive = item.id === activeRunId;

    const userTurn = document.createElement("button");
    userTurn.type = "button";
    userTurn.className = `chat-turn user message-turn${isActive ? " active" : ""}`;
    userTurn.dataset.runId = item.id;
    userTurn.innerHTML = `
      <div class="chat-label">用户 · ${escapeHtml(formatIsoLike(item.createdAt))}</div>
      <div class="chat-bubble markdown-body">${renderMarkdownHtml(item.goal || "")}</div>
    `;
    userTurn.addEventListener("click", () => {
      activeRunId = item.id;
      activeStepKey = null;
      saveActiveRunId();
      renderAll();
    });

    const assistantTurn = document.createElement("button");
    assistantTurn.type = "button";
    const isRunningTurn = item.result && item.result.status === "running";
    assistantTurn.className = `chat-turn assistant message-turn${isRunningTurn ? " is-running" : ""}${isActive ? " active" : ""}`;
    assistantTurn.dataset.runId = item.id;
    const answerText = isRunningTurn
      ? (item.result.progressText || "智能体思考中...")
      : (item.result && item.result.finalAnswer ? item.result.finalAnswer : item.result?.status || "(无回复)");
    // 用于复制的纯文本
    const answerPlainText = isRunningTurn
      ? ""
      : (item.result && item.result.finalAnswer ? item.result.finalAnswer : "");
    assistantTurn.innerHTML = `
      <div class="chat-label">助手</div>
      <div class="chat-bubble markdown-body">${renderMarkdownHtml(answerText)}</div>
      <div class="history-meta">${escapeHtml(item.result?.status || "-")} · ${escapeHtml(String(item.result?.durationMs || 0))} ms</div>
      <div class="chat-actions">
        <button type="button" class="chat-action-btn copy-btn" title="复制回复">📋 复制</button>
        <button type="button" class="chat-action-btn retry-btn" title="重新执行"${isRunning ? " disabled" : ""}>↻ 重试</button>
      </div>
    `;
    assistantTurn.addEventListener("click", () => {
      activeRunId = item.id;
      activeStepKey = null;
      saveActiveRunId();
      renderAll();
    });

    // 操作按钮事件
    const copyBtn = assistantTurn.querySelector(".copy-btn");
    const retryBtn = assistantTurn.querySelector(".retry-btn");
    if (copyBtn) {
      copyBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (answerPlainText) {
          void copyText(answerPlainText, copyBtn);
        }
      });
    }
    if (retryBtn && item.goal) {
      retryBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        void retryGoal(item.goal);
      });
    }

    timelineEl.appendChild(userTurn);
    timelineEl.appendChild(assistantTurn);
  }

  const visibleApprovals = getVisiblePendingApprovals();
  if (visibleApprovals.length) {
    for (const approvalEvent of visibleApprovals) {
      const approvalCard = document.createElement("div");
      approvalCard.className = "chat-turn assistant";

      const approvalLabel = document.createElement("div");
      approvalLabel.className = "chat-label";
      approvalLabel.textContent = "待审批";

      const wrap = document.createElement("div");
      wrap.className = "chat-approval-inline";

      // 审批提示（始终可见）
      const prompt = document.createElement("div");
      prompt.className = "approval-prompt";
      prompt.textContent = formatApprovalPrompt(approvalEvent);
      wrap.appendChild(prompt);

      // 可展开详情区域
      const details = document.createElement("details");
      details.className = "chat-approval-details";

      const summary = document.createElement("summary");
      summary.className = "chat-approval-summary";
      summary.textContent = "查看详情";
      details.appendChild(summary);

      const meta = document.createElement("pre");
      meta.className = "approval-meta";
      meta.textContent = formatApprovalMeta(approvalEvent);
      details.appendChild(meta);

      wrap.appendChild(details);

      // 决策按钮 — 动态生成，包含泛化选项
      const actions = document.createElement("div");
      actions.className = "chat-approval-actions";

      const dynamicDecisions = _buildApprovalDecisions(approvalEvent);
      for (const decision of dynamicDecisions) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = `approval-btn mini ${decision.cls}`.trim();
        btn.textContent = decision.label;
        btn.addEventListener("click", () => {
          void decideApproval(approvalEvent, decision.value);
        });
        actions.appendChild(btn);
      }

      wrap.appendChild(actions);
      approvalCard.appendChild(approvalLabel);
      approvalCard.appendChild(wrap);
      timelineEl.appendChild(approvalCard);
    }
  }

  const activeItem = sortedItems.find((item) => item.id === activeRunId) || sortedItems[0];
  if (!activeRunId && activeItem) {
    activeRunId = activeItem.id;
    saveActiveRunId();
  }
  renderInspector(getActiveStep(activeItem));

  // 聊天习惯：新消息出现在底部后自动滚到最下方
  timelineEl.scrollTop = timelineEl.scrollHeight;
}

function renderHistory() {
  historyListEl.innerHTML = "";
  const normalSessions = sessions.filter((item) => String(item.session_type || "normal") !== "schedule-runtime");
  if (!normalSessions.length) {
    historyListEl.innerHTML = "<div class='chat-empty'>暂无会话。先点击新建创建一个会话。</div>";
    return;
  }

  const pinned = normalSessions.filter((s) => s.pinned);
  const normal = normalSessions.filter((s) => !s.pinned);

  const renderGroup = (items, groupTitle) => {
    if (!items.length) {
      return;
    }
    const groupTitleEl = document.createElement("div");
    groupTitleEl.className = "session-group-title";
    groupTitleEl.textContent = groupTitle;
    historyListEl.appendChild(groupTitleEl);

    for (const item of items) {
      const isActiveSession = item.id === sessionSelectEl.value;
      const el = document.createElement("div");
      el.className = "history-item session-card";
      el.setAttribute("role", "button");
      el.tabIndex = 0;
      if (isActiveSession) {
        el.classList.add("active");
      }
      if (item.pinned) {
        el.classList.add("is-pinned");
      }

      const sessionName = escapeHtml(item.name || "未命名会话");
      el.innerHTML = `
        <div class="session-item-top">
          <button type="button" class="session-name-btn" aria-label="重命名会话">${sessionName}</button>
          <div class="session-actions">
            <button type="button" class="ghost-btn mini session-pin-btn ${item.pinned ? "is-active" : ""}" aria-label="${item.pinned ? "取消置顶" : "置顶会话"}" title="${item.pinned ? "取消置顶" : "置顶会话"}">📌</button>
            <button type="button" class="ghost-btn mini session-archive-btn" aria-label="归档会话" title="归档会话">📥</button>
            <button type="button" class="ghost-btn mini session-delete-btn" aria-label="删除会话" title="删除会话">🗑️</button>
          </div>
        </div>
      `;

      const selectSession = () => {
        sessionSelectEl.value = item.id;
        localStorage.setItem(SESSION_KEY, item.id);
        updateSessionHint();
        activeRunId = sessionRunItems.length ? sessionRunItems[sessionRunItems.length - 1].id : activeRunId;
        saveActiveRunId();
        loadSessionTasks(item.id).then(() => renderAll()).catch(() => renderAll());
        renderAll();
      };

      el.addEventListener("click", () => {
        selectSession();
      });

      el.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          selectSession();
        }
      });

      const deleteBtn = el.querySelector(".session-delete-btn");
      const pinBtn = el.querySelector(".session-pin-btn");
      const archiveBtn = el.querySelector(".session-archive-btn");
      const nameBtn = el.querySelector(".session-name-btn");

      if (pinBtn) {
        pinBtn.addEventListener("click", async (event) => {
          event.stopPropagation();
          pinBtn.disabled = true;
          try {
            await updateSessionStateById(item.id, { pinned: !item.pinned });
            await loadSessions(sessionSelectEl.value || item.id);
            sessionHintEl.textContent = item.pinned ? "会话已取消置顶" : "会话已置顶";
          } catch (_error) {
            pinBtn.disabled = false;
            sessionHintEl.textContent = "会话置顶状态更新失败";
          }
        });
      }

      if (archiveBtn) {
        let archiveConfirmTimer = null;
        const resetArchiveButton = () => {
          archiveBtn.dataset.confirming = "0";
          archiveBtn.classList.remove("is-pending");
          archiveBtn.textContent = "📥";
          archiveBtn.title = "归档会话";
        };

        archiveBtn.addEventListener("click", async (event) => {
          event.stopPropagation();

          if (archiveBtn.dataset.confirming !== "1") {
            archiveBtn.dataset.confirming = "1";
            archiveBtn.classList.add("is-pending");
            archiveBtn.textContent = "✓";
            archiveBtn.title = "再次点击确认归档";
            if (archiveConfirmTimer) {
              clearTimeout(archiveConfirmTimer);
            }
            archiveConfirmTimer = setTimeout(() => {
              resetArchiveButton();
            }, 3000);
            return;
          }

          if (archiveConfirmTimer) {
            clearTimeout(archiveConfirmTimer);
            archiveConfirmTimer = null;
          }

          archiveBtn.disabled = true;
          archiveBtn.textContent = "...";
          try {
            await updateSessionStateById(item.id, { archived: true });
            if (sessionSelectEl.value === item.id) {
              localStorage.removeItem(SESSION_KEY);
              sessionSelectEl.value = "";
              activeRunId = null;
              activeStepKey = null;
              sessionRunItems = [];
              saveActiveRunId();
            }
            await loadSessions(sessionSelectEl.value);
            sessionHintEl.textContent = "会话已归档，可到设置页恢复";
          } catch (_error) {
            archiveBtn.disabled = false;
            resetArchiveButton();
            sessionHintEl.textContent = "会话归档失败";
          }
        });
      }

      if (nameBtn) {
        nameBtn.title = "双击修改会话名称";
        nameBtn.addEventListener("click", (event) => {
          event.stopPropagation();
        });
        nameBtn.addEventListener("dblclick", (event) => {
          event.stopPropagation();
          event.preventDefault();
          const currentName = String(item.name || "").trim();
          if (!currentName || nameBtn.dataset.editing === "1") {
            return;
          }
          nameBtn.dataset.editing = "1";

          const input = document.createElement("input");
          input.type = "text";
          input.className = "session-name-inline-input";
          input.value = currentName;
          input.setAttribute("aria-label", "编辑会话名称");
          input.maxLength = 24;

          nameBtn.hidden = true;
          nameBtn.insertAdjacentElement("afterend", input);

          let finished = false;
          const finishEdit = async (commit) => {
            if (finished) {
              return;
            }
            finished = true;

            const nextName = String(input.value || "").trim();
            input.remove();
            nameBtn.hidden = false;
            nameBtn.dataset.editing = "0";

            if (!commit || !nextName || nextName === currentName) {
              return;
            }

            try {
              await renameSessionById(item.id, nextName);
              await loadSessions(sessionSelectEl.value || item.id);
              sessionHintEl.textContent = "会话名称已更新";
            } catch (_error) {
              sessionHintEl.textContent = "会话重命名失败";
            }
          };

          input.addEventListener("keydown", (keyEvent) => {
            keyEvent.stopPropagation();
            if (keyEvent.key === "Enter") {
              keyEvent.preventDefault();
              void finishEdit(true);
              return;
            }
            if (keyEvent.key === "Escape") {
              keyEvent.preventDefault();
              void finishEdit(false);
            }
          });

          input.addEventListener("mousedown", (mouseEvent) => {
            mouseEvent.stopPropagation();
          });
          input.addEventListener("click", (mouseEvent) => {
            mouseEvent.stopPropagation();
          });
          input.addEventListener("blur", () => {
            void finishEdit(true);
          });

          input.focus();
          input.select();
        });
      }

      if (deleteBtn) {
        let confirmTimer = null;
        const resetDeleteButton = () => {
          deleteBtn.dataset.confirming = "0";
          deleteBtn.classList.remove("is-pending");
          deleteBtn.textContent = "🗑️";
          deleteBtn.title = "删除会话";
        };

        deleteBtn.addEventListener("click", async (event) => {
          event.stopPropagation();
          if (deleteBtn.dataset.confirming !== "1") {
            deleteBtn.dataset.confirming = "1";
            deleteBtn.classList.add("is-pending");
            deleteBtn.textContent = "✓";
            deleteBtn.title = "再次点击确认删除";
            if (confirmTimer) {
              clearTimeout(confirmTimer);
            }
            confirmTimer = setTimeout(() => {
              resetDeleteButton();
            }, 3000);
            return;
          }

          if (confirmTimer) {
            clearTimeout(confirmTimer);
            confirmTimer = null;
          }

          deleteBtn.disabled = true;
          deleteBtn.textContent = "…";
          deleteBtn.title = "删除中";
          try {
            await deleteSessionById(item.id);
            if (sessionSelectEl.value === item.id) {
              localStorage.removeItem(SESSION_KEY);
              sessionSelectEl.value = "";
              activeRunId = null;
              activeStepKey = null;
              sessionRunItems = [];
              saveActiveRunId();
            }
            await loadSessions(sessionSelectEl.value);
            sessionHintEl.textContent = "会话已删除";
          } catch (_error) {
            deleteBtn.disabled = false;
            resetDeleteButton();
            sessionHintEl.textContent = "删除会话失败";
          }
        });
      }

      historyListEl.appendChild(el);
    }
  };

  renderGroup(pinned, "置顶会话");
  renderGroup(normal, "全部会话");
}

function renderAll() {
  const runItem = getCurrentRun();
  renderTimeline(runItem);
  renderHistory();
  renderRuntimeSessions();
  renderSchedulePanel();
  renderApprovalQueue();
  syncConsoleForActiveRun();
  if (typeof window._permTabRefresh === "function") window._permTabRefresh();
}

function pushRun(goal, result) {
  const runItem = {
    id: String(Date.now()),
    goal,
    createdAt: new Date().toISOString(),
    result,
  };
  historyItems = [runItem, ...historyItems].slice(0, 20);
  activeRunId = runItem.id;
  activeStepKey = null;
  liveRun = null;
  saveActiveRunId();
  saveHistory();
  renderAll();
}

function collectPayload() {
  const defaultMcpPath = String(mcpConfigState.defaultConfigPath || "").trim();
  return {
    goal: getValue("goal"),
    providerId: providerSelectEl.value || "",
    modelId: modelSelectEl.value || "",
    maxSteps: Number(getValue("maxSteps") || "50"),
    mcpConfig: defaultMcpPath || null,
    jsonMode: true,
  };
}

function normalizeApprovalDecision(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (["1", "2", "3", "4", "5", "6", "7", "y", "n"].includes(normalized)) {
    return normalized;
  }
  return "n";
}

async function submitApprovalDecision(runId, approvalId, decision) {
  const resp = await fetch(`/api/runs/${encodeURIComponent(runId)}/approvals/${encodeURIComponent(approvalId)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: "审批提交失败" }));
    throw new Error(err.detail || "审批提交失败");
  }
}

function approvalEventKey(event) {
  return `${event.run_id || "-"}:${event.approval_id || "-"}`;
}

function upsertPendingApproval(event) {
  const normalizedEvent = {
    ...event,
    session_id: String(event.session_id || getSessionIdFromRunId(event.run_id) || ""),
  };
  const key = approvalEventKey(event);
  const idx = pendingApprovals.findIndex((item) => approvalEventKey(item) === key);
  if (idx >= 0) {
    pendingApprovals[idx] = normalizedEvent;
  } else {
    pendingApprovals = [...pendingApprovals, normalizedEvent];
  }
  savePendingApprovals();
  renderApprovalQueue();
}

function removePendingApproval(runId, approvalId) {
  pendingApprovals = pendingApprovals.filter((item) => !(item.run_id === runId && item.approval_id === approvalId));
  savePendingApprovals();
  renderApprovalQueue();
}

function clearPendingApprovalsForRun(runId) {
  pendingApprovals = pendingApprovals.filter((item) => item.run_id !== runId);
  savePendingApprovals();
  renderApprovalQueue();
}

function formatRiskLevelLabel(risk) {
  const value = String(risk || "").toLowerCase();
  if (value === "low") {
    return "低";
  }
  if (value === "medium") {
    return "中";
  }
  if (value === "high") {
    return "高";
  }
  return risk || "-";
}

function formatApprovalPrompt(event) {
  const op = event.operation || {};
  if (op.tool || op.action || op.resource || op.risk) {
    const resourceLabel = op.resource ? `，目标资源「${op.resource}」` : "";
    const riskLabel = formatRiskLevelLabel(op.risk);
    return `请确认是否允许执行 ${op.tool || "-"}.${op.action || "-"}${resourceLabel}（风险：${riskLabel}）`;
  }

  const raw = String(event.prompt || "").trim();
  if (!raw) {
    return "请选择审批决策";
  }
  if (/tool:|action:|resource:|risk:|run_id:|approval_id:/i.test(raw)) {
    return "请确认该操作的执行权限";
  }
  return raw;
}

function formatApprovalMeta(event) {
  const op = event.operation || {};
  const lines = [
    `工具: ${op.tool || "-"}`,
    `动作: ${op.action || "-"}`,
    `资源: ${op.resource || "-"}`,
    `风险等级: ${formatRiskLevelLabel(op.risk)}`,
    `运行ID: ${event.run_id || currentRunServerId || "-"}`,
    `审批ID: ${event.approval_id || "-"}`,
  ];
  return lines.join("\n");
}

/**
 * 根据后端返回的 generalize_options 构建审批按钮列表。
 * 每项包含 scope（生命周期）和 resource_scope（资源范围）元数据。
 * 如果后端没返回 generalize_options（旧版兼容），使用默认列表。
 */
function _buildApprovalDecisions(event) {
  const opts = event.generalize_options;
  if (Array.isArray(opts) && opts.length > 0) {
    return opts.map((o) => {
      const decision = String(o.decision || "");
      const scope = o.scope || "once";
      const resourceScope = o.resource_scope || "exact";
      let cls = "";
      if (decision === "7" || decision === "n") cls = "err";
      else if (scope === "persistent" && decision === "6") cls = "";
      else if (scope === "persistent" && decision === "5") cls = "";
      else cls = "";
      return { label: o.label || decision, value: decision, cls, scope, resourceScope };
    });
  }
  // Fallback（旧版后端不返回 generalize_options）
  return [
    { label: "允许一次", value: "1", cls: "", scope: "once", resourceScope: "exact" },
    { label: "本会话允许", value: "2", cls: "", scope: "session", resourceScope: "exact" },
    { label: "始终允许", value: "6", cls: "", scope: "persistent", resourceScope: "exact_path" },
    { label: "始终拒绝", value: "7", cls: "err", scope: "persistent", resourceScope: "exact_path" },
  ];
}

function renderApprovalQueue() {
  approvalQueueEl.innerHTML = "";
  const visibleApprovals = getVisiblePendingApprovals();
  if (!visibleApprovals.length) {
    return;
  }

  for (const event of visibleApprovals) {
    const card = document.createElement("article");
    card.className = "approval-card";
    card.dataset.runId = event.run_id || "";
    card.dataset.approvalId = event.approval_id || "";

    const head = document.createElement("div");
    head.className = "approval-card-head";
    head.textContent = "HUMAN IN THE LOOP";

    const title = document.createElement("h3");
    title.className = "approval-title";
    title.textContent = "待审批操作";

    const prompt = document.createElement("p");
    prompt.className = "approval-prompt";
    prompt.textContent = formatApprovalPrompt(event);

    const meta = document.createElement("pre");
    meta.className = "approval-meta";
    meta.textContent = formatApprovalMeta(event);

    const actions = document.createElement("div");
    actions.className = "approval-actions";

    // 动态生成按钮：优先用后端返回的 generalize_options，否则 fallback
    const dynamicDecisions = _buildApprovalDecisions(event);
    for (const item of dynamicDecisions) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `approval-btn ${item.cls}`.trim();
      btn.textContent = item.label;
      btn.addEventListener("click", () => {
        decideApproval(event, item.value);
      });
      actions.appendChild(btn);
    }

    card.appendChild(head);
    card.appendChild(title);
    card.appendChild(prompt);
    card.appendChild(meta);
    card.appendChild(actions);
    approvalQueueEl.appendChild(card);
  }
}

function focusApprovalCard(runId, approvalId) {
  switchTab("console");
  renderAll();

  requestAnimationFrame(() => {
    const cards = Array.from(approvalQueueEl.querySelectorAll(".approval-card"));
    if (!cards.length) {
      return;
    }
    const target = cards.find((card) => card.dataset.runId === runId && card.dataset.approvalId === approvalId) || cards[0];
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    target.classList.add("flash-focus");
    setTimeout(() => {
      target.classList.remove("flash-focus");
    }, 1200);
  });
}

async function decideApproval(event, decision) {
  if (!event) {
    return;
  }

  const normalized = normalizeApprovalDecision(decision);
  const runId = event.run_id;
  const approvalId = event.approval_id;

  try {
    await submitApprovalDecision(runId, approvalId, normalized);
    const isDeny = ["n", "7"].includes(normalized);
    appendConsoleLine("GATE", `已提交审批决策: ${normalized}`, isDeny ? "err" : "ok");
    removePendingApproval(runId, approvalId);
    renderAll();
  } catch (error) {
    appendConsoleLine("ERROR", `审批提交失败: ${error.message}`, "err");
  }
}

function validatePayload(payload) {
  if (!payload.goal) {
    throw new Error("请输入问题或任务请求。");
  }
  if (!payload.providerId || !payload.modelId) {
    throw new Error("请先选择 provider 和模型。")
  }
}

/**
 * 执行目标：创建会话、发送请求、处理流式响应。
 * 供 runReact（发送）和重试按钮复用。
 */
async function executeGoal(goal) {
  const sessionId = await ensureSessionIdForRun();
  localStorage.setItem(SESSION_KEY, sessionId);
  updateSessionHint();

  setRunning(true);

  beginLiveRun(goal);
  updateLiveProgress("任务已提交，准备连接后端流...");
  consoleSnapshotRunId = null;
  setValue("goal", "");
  renderAll();

  currentAbortController = new AbortController();

  // 使用 FormData 支持 multipart 文件上传
  const form = new FormData();
  form.append("goal", goal);
  for (const item of pendingFiles) {
    form.append("files", item.file, item.file.name);
  }
  clearPendingFiles();

  const resp = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/tasks`, {
    method: "POST",
    body: form,
    signal: currentAbortController.signal,
  });

  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: "请求失败" }));
    throw new Error(err.detail || "请求失败");
  }

  if (!resp.body) {
    throw new Error("服务端未返回流式数据");
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

    let newlineIndex = buffer.indexOf("\n");
    while (newlineIndex !== -1) {
      const line = buffer.slice(0, newlineIndex).trim();
      buffer = buffer.slice(newlineIndex + 1);
      if (line) {
        handleStreamEvent(JSON.parse(line));
      }
      newlineIndex = buffer.indexOf("\n");
    }

    if (done) {
      const tail = buffer.trim();
      if (tail) {
        handleStreamEvent(JSON.parse(tail));
      }
      break;
    }
  }
}

/** 通用错误处理包装（供 runReact 和 retryGoal 复用） */
function handleRunError(error) {
  if (error instanceof DOMException && error.name === "AbortError") {
    return;
  }
  appendConsoleLine("ERROR", error.message, "err");
  if (liveRun) {
    liveRun.result.status = "error";
    liveRun.result.finalAnswer = `任务执行异常：${error.message}`;
    liveRun.result.durationMs = Math.max(0, Date.now() - currentRunStartMs);
    renderAll();
  }
}

/** 重试：用原始 goal 重新执行 */
async function retryGoal(goal) {
  if (isRunning) return;
  try {
    await executeGoal(goal);
  } catch (error) {
    handleRunError(error);
  } finally {
    setRunning(false);
    renderAll();
  }
}

async function runReact() {
  const payload = collectPayload();
  try {
    validatePayload(payload);
  } catch (error) {
    appendConsoleLine("ERROR", error.message, "err");
    return;
  }

  try {
    const handled = await tryHandleScheduleCreateByChat(payload.goal);
    if (handled) {
      setValue("goal", "");
      return;
    }
  } catch (error) {
    appendConsoleLine("ERROR", `创建定时任务失败: ${error.message}`, "err");
    return;
  }

  try {
    await executeGoal(payload.goal);
  } catch (error) {
    handleRunError(error);
  } finally {
    setRunning(false);
    renderAll();
  }
}

function handleStreamEvent(event) {
  if (event && typeof event === "object") {
    if (!liveRun) {
      beginLiveRun("unknown");
    }
    if (!Array.isArray(liveRun.result.events)) {
      liveRun.result.events = [];
    }
    try {
      liveRun.result.events.push(JSON.parse(JSON.stringify(event)));
    } catch (_error) {
      liveRun.result.events.push(event);
    }
  }

  switch (event.type) {
    case "session_renamed":
      if (event.session_id && event.name) {
        appendConsoleLine("SESSION", `会话已重命名：${event.name}`, "ok");
        if (sessionSelectEl.value === event.session_id) {
          sessionHintEl.textContent = `会话名称已自动更新为：${event.name}`;
        }
        loadSessions(sessionSelectEl.value || event.session_id).then(() => renderAll()).catch(() => null);
      }
      break;
    case "run_boot":
      currentRunServerId = event.run_id || null;
      currentRunTaskId = event.task_id || null;
      updateLiveProgress("任务已启动，正在拆解步骤...");
      appendConsoleBlock("BOOT", "开始任务", [`goal: ${event.goal}`], "dim");
      renderAll();
      break;
    case "approval_required":
      updateLiveProgress(`等待审批：${(event.operation || {}).tool || "-"}.${(event.operation || {}).action || "-"}`);
      appendConsoleBlock(
        "GATE",
        "等待人工审批",
        [
          `运行ID: ${event.run_id || currentRunServerId || "-"}`,
          `审批ID: ${event.approval_id || "-"}`,
          `操作: ${(event.operation || {}).tool || "-"}.${(event.operation || {}).action || "-"}`,
        ],
        "dim",
      );
      upsertPendingApproval(event);
      renderAll();
      break;
    case "approval_timeout":
      updateLiveProgress("审批超时，已按默认策略处理...");
      appendConsoleBlock(
        "GATE",
        "审批超时，默认拒绝",
        [`审批ID: ${event.approval_id || "-"}`, `决策: ${event.default_decision || "n"}`],
        "err",
      );
      removePendingApproval(event.run_id, event.approval_id);
      renderAll();
      break;
    case "run_start":
      updateLiveProgress("任务已接收，开始执行...");
      appendConsoleBlock("RUN", "任务已接收", [`goal: ${event.goal}`], "dim");
      renderAll();
      break;
    case "step_start":
      updateLiveProgress(`正在执行 Step ${event.step}...`);
      appendConsoleBlock("STEP", `Step ${event.step}`, ["state: start"], "dim");
      renderAll();
      break;
    case "llm_pending":
      updateLiveProgress(`Step ${event.step}：等待模型响应...`);
      appendConsoleBlock("LLM", `Step ${event.step} 等待模型响应`, ["state: pending"], "dim");
      renderAll();
      break;
    case "llm_response":
      updateLiveProgress(`Step ${event.step}：模型已响应，准备执行动作...`);
      appendConsoleBlock("LLM", `Step ${event.step} 模型响应`, ["state: received", `bytes: ${String(event.content || "").length}`], "dim");
      renderAll();
      break;
    case "action_start":
      updateLiveProgress(`执行工具：${(event.operation || {}).tool || "-"}.${(event.operation || {}).action || "-"}`);
      appendConsoleBlock(
        "CMD",
        toShellCommand(event.operation),
        summarizeOperation(event.operation),
        "dim",
      );
      renderAll();
      break;
    case "approval":
      updateLiveProgress(event.approved ? "审批通过，继续执行..." : "审批拒绝，等待下一步...");
      appendConsoleBlock(
        "GATE",
        event.approved ? "Policy Guard: approved" : "Policy Guard: rejected",
        [
          `step: ${event.step}`,
          `tool_call_id: ${event.tool_call_id || "-"}`,
          `decision: ${event.approved ? "allow" : "deny"}`,
          `operation: ${event.operation.tool}.${event.operation.action}`,
        ],
        event.approved ? "ok" : "err",
      );
      renderAll();
      break;
    case "action_result": {
      const status = event.observation && event.observation.ok ? "ok" : "err";
      updateLiveProgress(status === "ok" ? "工具执行成功，继续处理中..." : "工具执行失败，正在恢复流程...");
      appendConsoleBlock(
        "OBS",
        status === "ok" ? "Tool result" : "Tool error",
        summarizeObservation(event.observation),
        status,
      );
      renderAll();
      break;
    }
    case "step_complete":
      if (!liveRun) {
        beginLiveRun("unknown");
      }
      liveRun.result.steps.push(event.step_record);
      updateLiveProgress(`Step ${event.step} 已完成，准备下一步...`);
      appendConsoleBlock(
        "STEP",
        `Step ${event.step} completed`,
        [
          `records: ${Array.isArray(event.step_record.operations) ? event.step_record.operations.length : 1}`,
          `tool_call_id: ${event.step_record.tool_call_id || (Array.isArray(event.step_record.tool_call_ids) ? event.step_record.tool_call_ids.join(",") : "-")}`,
        ],
        "ok",
      );
      renderAll();
      break;
    case "run_complete": {
      if (!liveRun) {
        beginLiveRun("unknown");
      }
      liveRun.result.status = event.status;
      liveRun.result.finalAnswer = event.final_answer;
      liveRun.result.durationMs = event.duration_ms || Math.max(0, Date.now() - currentRunStartMs);
      liveRun.result.steps = event.steps || liveRun.result.steps;
      appendConsoleBlock("DONE", "任务完成", [`status: ${event.status}`, `final_answer: ${event.final_answer}`], "ok");
      pushRun(liveRun.goal, liveRun.result);
      clearPendingApprovalsForRun(event.run_id || currentRunServerId || "");
      if (sessionSelectEl.value) {
        loadSessions(sessionSelectEl.value).catch(() => null);
        setTimeout(() => {
          loadSessions(sessionSelectEl.value).catch(() => null);
        }, 1500);
        loadSessionTasks(sessionSelectEl.value).then(() => {
          loadSessionSchedules(sessionSelectEl.value).catch(() => null);
          if (currentRunTaskId) {
            activeRunId = `task:${currentRunTaskId}`;
            saveActiveRunId();
          }
          renderAll();
        }).catch(() => null);
      }
      currentRunTaskId = null;
      currentRunServerId = null;
      break;
    }
    case "run_error":
      if (!liveRun) {
        beginLiveRun("unknown");
      }
      liveRun.result.status = "error";
      liveRun.result.finalAnswer = event.message;
      liveRun.result.durationMs = Math.max(0, Date.now() - currentRunStartMs);
      appendConsoleBlock("DONE", "任务失败", [`error: ${event.message}`], "err");
      pushRun(liveRun.goal, liveRun.result);
      clearPendingApprovalsForRun(currentRunServerId || "");
      if (sessionSelectEl.value) {
        loadSessions(sessionSelectEl.value).catch(() => null);
        loadSessionTasks(sessionSelectEl.value).catch(() => null);
      }
      currentRunTaskId = null;
      currentRunServerId = null;
      break;
    default:
      appendConsoleLine("INFO", summarizeObject(event), "dim");
      break;
  }
}

async function copyText(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
    const prev = btn.textContent;
    btn.textContent = "已复制";
    setTimeout(() => {
      btn.textContent = prev;
    }, 900);
  } catch (_error) {
    appendConsoleLine("ERROR", "复制失败：当前环境可能不支持剪贴板权限。", "err");
  }
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderMarkdownHtml(text) {
  const raw = String(text || "");
  if (!raw.trim()) {
    return "";
  }

  let html = "";
  if (window.marked && typeof window.marked.parse === "function") {
    html = window.marked.parse(raw, {
      gfm: true,
      breaks: true,
      mangle: false,
      headerIds: false,
    });
  } else {
    html = escapeHtml(raw).replaceAll("\n", "<br />");
  }

  if (window.DOMPurify && typeof window.DOMPurify.sanitize === "function") {
    return window.DOMPurify.sanitize(html, {
      USE_PROFILES: { html: true },
      FORBID_TAGS: ["style", "script"],
      FORBID_ATTR: ["style", "onerror", "onload", "onclick"],
    });
  }

  return html;
}

runBtn.addEventListener("click", () => {
  if (isRunning) {
    stopCurrentRun();
  } else {
    runReact();
  }
});

if (createSessionBtn) {
  createSessionBtn.addEventListener("click", async () => {
    try {
      await createSession("", "");
      setValue("goal", "");
      sessionHintEl.textContent = "已创建新会话";
      // 新建会话时重置控制台
      clearConsole();
      consoleSnapshotRunId = null;
    } catch (_error) {
      sessionHintEl.textContent = "创建会话失败";
    }
  });
}

if (createSessionFromScheduleBtn) {
  createSessionFromScheduleBtn.addEventListener("click", async () => {
    try {
      const createdId = await createSession("定时任务会话", "", { sessionType: "schedule-runtime" });
      switchRailTab("schedules");
      sessionSelectEl.value = createdId;
      localStorage.setItem(SESSION_KEY, createdId);
      setValue("goal", "");
      if (scheduleHintEl) {
        scheduleHintEl.textContent = "已新建定时任务会话。现在可以在这个会话里创建和管理定时任务。";
      }
      clearConsole();
      consoleSnapshotRunId = null;
      await loadRuntimeSessions();
      renderAll();
    } catch (_error) {
      if (scheduleHintEl) {
        scheduleHintEl.textContent = "创建会话失败";
      }
    }
  });
}

refreshSessionsBtn.addEventListener("click", () => {
  loadSessions(sessionSelectEl.value).catch(() => {
    sessionHintEl.textContent = "刷新会话失败";
  });
});

sessionSelectEl.addEventListener("change", async () => {
  const selectedId = sessionSelectEl.value;
  localStorage.setItem(SESSION_KEY, selectedId);
  updateSessionHint();
  await loadSessionTasks(selectedId);
  await loadSessionSchedules(selectedId);
  await syncPendingApprovalsForSession(selectedId);
  activeRunId = sessionRunItems.length ? sessionRunItems[sessionRunItems.length - 1].id : activeRunId;
  renderAll();
});

if (refreshSchedulesBtn) {
  refreshSchedulesBtn.addEventListener("click", async () => {
    const selectedId = String(sessionSelectEl.value || "").trim();
    if (!selectedId) {
      if (scheduleHintEl) {
        scheduleHintEl.textContent = "请先选择会话。";
      }
      return;
    }
    await loadSessionSchedules(selectedId);
    if (scheduleHintEl) {
      scheduleHintEl.textContent = "定时任务已刷新。";
    }
    renderSchedulePanel();
  });
}

if (railTabSessionsEl) {
  railTabSessionsEl.addEventListener("click", () => {
    switchRailTab("sessions");
  });
}

if (railTabSchedulesEl) {
  railTabSchedulesEl.addEventListener("click", () => {
    switchRailTab("schedules");
    renderSchedulePanel();
  });
}

providerSelectEl.addEventListener("change", () => {
  localStorage.setItem(PROVIDER_KEY, providerSelectEl.value);
  renderModelSelectorForProvider(providerSelectEl.value);
  pushModelSwitch(getSelectedProviderAndModel());
  updateModelProfileHint();
});

modelSelectEl.addEventListener("change", () => {
  localStorage.setItem(MODEL_KEY, modelSelectEl.value);
  pushModelSwitch(getSelectedProviderAndModel());
  updateModelProfileHint();
});

maxStepsEl.addEventListener("input", () => {
  renderConfigCapsules();
});

function loadModelConfigForProvider(providerId) {
  renderModelSelectorForProvider(providerId);
  pushModelSwitch(getSelectedProviderAndModel());
  updateModelProfileHint();
}

// Popover management
function closeAllPopovers() {
  if (sessionPopoverEl) sessionPopoverEl.hidden = true;
  if (modelPopoverEl) modelPopoverEl.hidden = true;
}

function openPopover(popoverEl, triggerEl) {
  if (!popoverEl || !triggerEl) return;

  if (!popoverEl.hidden) {
    closeAllPopovers();
    return;
  }

  closeAllPopovers();
  popoverEl.hidden = false;
  const rect = triggerEl.getBoundingClientRect();
  popoverEl.style.bottom = `${window.innerHeight - rect.top + 8}px`;
  popoverEl.style.left = `${Math.max(16, rect.left - 80)}px`;
}

function setupPopoverClosers() {
  document.querySelectorAll(".popover-close").forEach((btn) => {
    btn.addEventListener("click", closeAllPopovers);
  });
}

document.addEventListener("click", (e) => {
  const popovers = [sessionPopoverEl, modelPopoverEl];
  const chips = [configChipModelEl];
  
  if (![...popovers, ...chips].some((el) => el?.contains(e.target))) {
    closeAllPopovers();
  }
});

if (configChipModelEl) {
  configChipModelEl.addEventListener("click", () => {
    openPopover(modelPopoverEl, configChipModelEl);
    requestAnimationFrame(() => {
      modelSelectPopoverEl?.focus();
    });
  });
}

setupPopoverClosers();

// Legacy popover-less selects (keep in sync with popovers)
if (sessionSelectPopoverEl) {
  sessionSelectPopoverEl.addEventListener("change", () => {
    if (sessionSelectEl) sessionSelectEl.value = sessionSelectPopoverEl.value;
    localStorage.setItem(SESSION_KEY, sessionSelectPopoverEl.value);
    const selectedId = sessionSelectPopoverEl.value;
    if (selectedId) {
      loadSessionTasks(selectedId)
        .then(() => syncPendingApprovalsForSession(selectedId))
        .then(() => renderAll())
        .catch(() => renderAll());
    }
    renderConfigCapsules();
  });
}

if (providerSelectPopoverEl) {
  providerSelectPopoverEl.addEventListener("change", () => {
    if (providerSelectEl) providerSelectEl.value = providerSelectPopoverEl.value;
    localStorage.setItem(PROVIDER_KEY, providerSelectPopoverEl.value);
    loadModelConfigForProvider(providerSelectPopoverEl.value);
    renderConfigCapsules();
  });
}

if (modelSelectPopoverEl) {
  modelSelectPopoverEl.addEventListener("change", () => {
    if (modelSelectEl) modelSelectEl.value = modelSelectPopoverEl.value;
    localStorage.setItem(MODEL_KEY, modelSelectPopoverEl.value);
    renderConfigCapsules();
  });
}

function loadQuickPrompts() {
  try {
    const raw = localStorage.getItem(QUICK_PROMPTS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch (_error) {
    return [];
  }
}

function renderGoalChips() {
  const container = document.getElementById("goalChips");
  if (!container) return;
  container.innerHTML = "";
  const prompts = loadQuickPrompts();
  for (const item of prompts) {
    const btn = document.createElement("button");
    btn.className = "chip";
    btn.dataset.goal = item.goal || "";
    btn.textContent = item.label || "";
    btn.addEventListener("click", () => {
      setValue("goal", item.goal || "");
    });
    container.appendChild(btn);
  }
}

renderGoalChips();

goalEl.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    runBtn.click();
  }
});

// 标签页事件监听器
debugTabButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    const tabName = btn.dataset.tab;
    switchTab(tabName);
  });
});

loadActiveTab();
loadActiveRailTab();
renderTabs();
renderRailTabs();

checkHealth();
loadModelConfig();
loadMcpConfig();
loadSessions();
renderConfigCapsules();
renderAll();

// 页面加载后立即同步当前会话的 pending approvals，确保刷新后审批卡片仍可见
setTimeout(() => {
  const initialSessionId = sessionSelectEl.value;
  if (initialSessionId) {
    syncPendingApprovalsForSession(initialSessionId).catch(() => null);
  }
}, 500);
