const runBtn = document.getElementById("runBtn");
const clearHistoryBtn = document.getElementById("clearHistoryBtn");
const timelineEl = document.getElementById("timeline");
const historyListEl = document.getElementById("historyList");
const healthBadgeEl = document.getElementById("healthBadge");
const stepTemplate = document.getElementById("stepTemplate");
const clearConsoleBtn = document.getElementById("clearConsoleBtn");
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
const sessionMetaEl = document.getElementById("sessionMeta");
const sessionMetaInlineEl = document.getElementById("sessionMetaInline");
const configChipModelEl = document.getElementById("configChipModel");
const configChipStepsEl = document.getElementById("configChipSteps");
const configChipModelLabelEl = document.getElementById("configChipModelLabel");
const configChipStepsLabelEl = document.getElementById("configChipStepsLabel");
const createSessionBtn = document.getElementById("createSessionBtn");
const refreshSessionsBtn = document.getElementById("refreshSessionsBtn");
const goalEl = document.getElementById("goal");
const goalChips = Array.from(document.querySelectorAll(".chip"));
const debugTabButtons = Array.from(document.querySelectorAll(".debug-tab-btn"));

// Popover elements
const sessionPopoverEl = document.getElementById("sessionPopover");
const modelPopoverEl = document.getElementById("modelPopover");
const stepsPopoverEl = document.getElementById("stepsPopover");
const sessionSelectPopoverEl = document.getElementById("sessionSelectPopover");
const providerSelectPopoverEl = document.getElementById("providerSelectPopover");
const modelSelectPopoverEl = document.getElementById("modelSelectPopover");
const currentModelTagPopoverEl = document.getElementById("currentModelTagPopover");
const maxStepsPopoverEl = document.getElementById("maxStepsPopover");
const maxStepsSliderEl = document.getElementById("maxStepsSlider");
const maxStepsValueEl = document.getElementById("maxStepsValue");

const HISTORY_KEY = "myclaw-agent-history-v1";
const PROVIDER_KEY = "myclaw-selected-provider";
const MODEL_KEY = "myclaw-selected-model";
const MODEL_SWITCHES_KEY = "myclaw-model-switches-v1";
const SESSION_KEY = "myclaw-selected-session";
const ACTIVE_TAB_KEY = "myclaw-active-tab";
const ACTIVE_RUN_KEY = "myclaw-active-run-id";

let historyItems = loadHistory();
let activeRunId = loadActiveRunId() || (historyItems.length ? historyItems[0].id : null);
let activeStepKey = null;
let isRunning = false;
let currentRunStartMs = 0;
let liveRun = null;
let currentRunServerId = null;
let pendingApprovals = [];
let modelConfig = { defaultProfileId: "", defaultModelId: "", providers: [] };
let mcpConfigState = { defaultConfigPath: "", servers: [] };
let recentModelSwitches = loadRecentModelSwitches();
let sessions = [];
let sessionRunItems = [];
let currentRunTaskId = null;
let activeTab = "chat";
let consoleSnapshotRunId = null;

function switchTab(tabName) {
  if (activeTab === tabName) return;
  activeTab = tabName;
  saveActiveTab();
  renderTabs();
}

function saveActiveTab() {
  localStorage.setItem(ACTIVE_TAB_KEY, activeTab);
}

function loadActiveTab() {
  const saved = localStorage.getItem(ACTIVE_TAB_KEY);
  if (saved && ["chat", "console"].includes(saved)) {
    activeTab = saved;
  }
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
  runBtn.disabled = running;
  runBtn.textContent = running ? "发送中..." : "发送";
  if (running) {
    currentRunStartMs = Date.now();
  }
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

function renderConsoleFromRun(runItem) {
  clearConsole();
  if (!runItem) {
    return;
  }

  const status = runItem.result?.status || "unknown";
  const tone = status === "completed" ? "ok" : status === "error" ? "err" : "dim";
  appendConsoleBlock(
    "HISTORY",
    "历史任务概览",
    [
      `goal: ${runItem.goal || "-"}`,
      `status: ${status}`,
      `duration_ms: ${runItem.result?.durationMs || 0}`,
      `created_at: ${runItem.createdAt || "-"}`,
    ],
    tone,
  );

  const steps = Array.isArray(runItem.result?.steps) ? runItem.result.steps : [];
  if (!steps.length) {
    appendConsoleLine("HISTORY", "该任务没有保存步骤数据", "dim");
  }

  for (const step of steps) {
    const pairs = getStepOperationPairs(step);
    if (!pairs.length) {
      appendConsoleBlock("STEP", `Step ${step.step || "-"}`, ["no operation records"], "dim");
      continue;
    }

    pairs.forEach((pair, idx) => {
      const operationLines = summarizeOperation(pair.operation);
      const observationLines = summarizeObservation(pair.observation);
      const policyDecision = inferPolicyDecision(pair.observation);
      const statusTone = pair.observation && pair.observation.ok ? "ok" : pair.observation?.error ? "err" : "dim";
      appendConsoleBlock(
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
    appendConsoleBlock("DONE", "历史最终回答", [`final_answer: ${runItem.result.finalAnswer}`], tone);
  }
}

function syncConsoleForActiveRun() {
  const runItem = getCurrentRun();
  if (!runItem) {
    return;
  }

  const runId = String(runItem.id || "");
  const isLiveRunning = !!liveRun && liveRun.id === runId && isRunning;
  if (isLiveRunning) {
    consoleSnapshotRunId = null;
    return;
  }

  if (consoleSnapshotRunId === runId) {
    return;
  }

  renderConsoleFromRun(runItem);
  consoleSnapshotRunId = runId;
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
    ["tool", operation.tool],
    ["action", operation.action],
    ["resource", operation.resource],
    ["risk", operation.risk],
    ["params", summarizeObject(operation.params)],
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
    modelConfig = { defaultProfileId: "", defaultModelId: "", providers: [] };
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

function updateSessionHint() {
  const selectedId = sessionSelectEl.value;
  const selected = sessions.find((item) => item.id === selectedId);
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

function renderConfigCapsules() {
  const selectedId = sessionSelectEl.value;
  const selectedSession = sessions.find((item) => item.id === selectedId);
  const selectedModel = getSelectedProviderAndModel();
  const steps = Number(maxStepsEl.value || "8");

  if (configChipModelLabelEl) {
    configChipModelLabelEl.textContent = selectedModel ? `模型: ${selectedModel.model.name}` : "模型: -";
  }
  if (configChipStepsLabelEl) {
    configChipStepsLabelEl.textContent = `步数: ${steps}`;
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
    option.textContent = `${session.name} (${session.task_count || 0})`;
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
    const resp = await fetch("/api/sessions?limit=50");
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

async function createSession(preferredName = "", seedGoal = "") {
  const name = String(preferredName || "").trim();
  const resp = await fetch("/api/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name,
      seedGoal: String(seedGoal || "").trim(),
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
  await loadSessionTasks(created.id);
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
    : providerIds.has(modelConfig.defaultProfileId)
      ? modelConfig.defaultProfileId
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
    option.textContent = `${model.name} (${model.model})`;
    modelSelectEl.appendChild(option);
    if (modelSelectPopoverEl) modelSelectPopoverEl.appendChild(option.cloneNode(true));
  }

  const rememberedModel = localStorage.getItem(MODEL_KEY);
  const modelIds = new Set(provider.models.map((item) => item.id));
  const selectedModelId = modelIds.has(rememberedModel)
    ? rememberedModel
    : provider.id === modelConfig.defaultProfileId && modelIds.has(modelConfig.defaultModelId)
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

function renderTimeline(runItem) {
  timelineEl.innerHTML = "";
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

  if (!conversationItems.length) {
    timelineEl.innerHTML = "<div class='chat-empty'>暂无对话。先在底部输入消息并发送。</div>";
    renderInspector(null);
    return;
  }

  const sortedItems = conversationItems
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
    .map((entry) => entry.item)
    .filter((item, idx, arr) => arr.findIndex((one) => one.id === item.id) === idx);

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
    assistantTurn.innerHTML = `
      <div class="chat-label">助手</div>
      <div class="chat-bubble markdown-body">${renderMarkdownHtml(answerText)}</div>
      <div class="history-meta">${escapeHtml(item.result?.status || "-")} · ${escapeHtml(String(item.result?.durationMs || 0))} ms</div>
    `;
    assistantTurn.addEventListener("click", () => {
      activeRunId = item.id;
      activeStepKey = null;
      saveActiveRunId();
      renderAll();
    });

    timelineEl.appendChild(userTurn);
    timelineEl.appendChild(assistantTurn);
  }

  if (pendingApprovals.length) {
    const firstApproval = pendingApprovals[0];
    const pendingCard = document.createElement("div");
    pendingCard.className = "chat-turn assistant";

    const label = document.createElement("div");
    label.className = "chat-label";
    label.textContent = "待审批";

    const wrap = document.createElement("div");
    wrap.className = "chat-approval-inline";

    const hint = document.createElement("div");
    hint.className = "chat-approval-hint";
    hint.textContent = `当前有 ${pendingApprovals.length} 条待审批操作`;
    wrap.appendChild(hint);

    const actions = document.createElement("div");
    actions.className = "chat-approval-actions";

    const jumpBtn = document.createElement("button");
    jumpBtn.type = "button";
    jumpBtn.className = "ghost-btn";
    jumpBtn.textContent = "去控制台审批";
    jumpBtn.addEventListener("click", () => {
      focusApprovalCard(firstApproval.run_id, firstApproval.approval_id);
    });
    actions.appendChild(jumpBtn);

    const decisions = [
      { label: "允许一次", value: "1", cls: "ok" },
      { label: "会话允许", value: "2", cls: "" },
      { label: "始终允许", value: "3", cls: "" },
      { label: "拒绝", value: "n", cls: "err" },
    ];

    for (const decision of decisions) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `approval-btn mini ${decision.cls}`.trim();
      btn.textContent = decision.label;
      btn.addEventListener("click", () => {
        void decideApproval(firstApproval, decision.value);
      });
      actions.appendChild(btn);
    }

    wrap.appendChild(actions);
    pendingCard.appendChild(label);
    pendingCard.appendChild(wrap);
    timelineEl.appendChild(pendingCard);
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
  const sourceItems = sessions;

  if (!sourceItems.length) {
    historyListEl.innerHTML = "<div class='chat-empty'>暂无会话。先点击新建创建一个会话。</div>";
    return;
  }

  for (const item of sourceItems) {
    const el = document.createElement("div");
    el.className = "history-item";
    el.setAttribute("role", "button");
    el.tabIndex = 0;
    if (item.id === sessionSelectEl.value) {
      el.classList.add("active");
    }
    const sessionName = escapeHtml(item.name || "未命名会话");
    const updatedAt = escapeHtml(formatIsoLike(item.updated_at));
    const taskCount = escapeHtml(String(item.task_count || 0));
    el.innerHTML = `
      <div class="session-item-top">
        <button type="button" class="session-name-btn" aria-label="重命名会话">${sessionName}</button>
        <div class="session-actions">
          <span class="session-item-badge">${taskCount}</span>
          <button type="button" class="ghost-btn mini session-delete-btn" aria-label="删除会话" title="删除会话">×</button>
        </div>
      </div>
      <div class="history-meta">更新于 ${updatedAt}</div>
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
    const nameBtn = el.querySelector(".session-name-btn");

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
        deleteBtn.textContent = "×";
        deleteBtn.title = "删除会话";
      };

      deleteBtn.addEventListener("click", async (event) => {
        event.stopPropagation();
        if (deleteBtn.dataset.confirming !== "1") {
          deleteBtn.dataset.confirming = "1";
          deleteBtn.classList.add("is-pending");
          deleteBtn.textContent = "×";
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
}

function renderAll() {
  const runItem = getCurrentRun();
  renderTimeline(runItem);
  renderHistory();
  syncConsoleForActiveRun();
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
    maxSteps: Number(getValue("maxSteps") || "8"),
    mcpConfig: defaultMcpPath || null,
    jsonMode: true,
  };
}

function normalizeApprovalDecision(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (["1", "2", "3", "4", "y", "n"].includes(normalized)) {
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
  const key = approvalEventKey(event);
  const idx = pendingApprovals.findIndex((item) => approvalEventKey(item) === key);
  if (idx >= 0) {
    pendingApprovals[idx] = event;
  } else {
    pendingApprovals = [...pendingApprovals, event];
  }
  renderApprovalQueue();
}

function removePendingApproval(runId, approvalId) {
  pendingApprovals = pendingApprovals.filter((item) => !(item.run_id === runId && item.approval_id === approvalId));
  renderApprovalQueue();
}

function clearPendingApprovalsForRun(runId) {
  pendingApprovals = pendingApprovals.filter((item) => item.run_id !== runId);
  renderApprovalQueue();
}

function formatApprovalMeta(event) {
  const op = event.operation || {};
  const lines = [
    `tool: ${op.tool || "-"}`,
    `action: ${op.action || "-"}`,
    `resource: ${op.resource || "-"}`,
    `risk: ${op.risk || "-"}`,
    `run_id: ${event.run_id || currentRunServerId || "-"}`,
    `approval_id: ${event.approval_id || "-"}`,
  ];
  return lines.join("\n");
}

function renderApprovalQueue() {
  approvalQueueEl.innerHTML = "";
  if (!pendingApprovals.length) {
    return;
  }

  const decisions = [
    { label: "允许一次", value: "1", cls: "ok" },
    { label: "会话允许", value: "2", cls: "" },
    { label: "始终允许", value: "3", cls: "" },
    { label: "始终拒绝", value: "4", cls: "err" },
    { label: "拒绝", value: "n", cls: "err" },
  ];

  for (const event of pendingApprovals) {
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
    prompt.textContent = event.prompt || "请选择审批决策";

    const meta = document.createElement("pre");
    meta.className = "approval-meta";
    meta.textContent = formatApprovalMeta(event);

    const actions = document.createElement("div");
    actions.className = "approval-actions";

    for (const item of decisions) {
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
    appendConsoleLine("GATE", `已提交审批决策: ${normalized}`, normalized === "n" || normalized === "4" ? "err" : "ok");
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

async function runReact() {
  const payload = collectPayload();
  try {
    validatePayload(payload);
  } catch (error) {
    appendConsoleLine("ERROR", error.message, "err");
    return;
  }

  try {
    const sessionId = await ensureSessionIdForRun();
    localStorage.setItem(SESSION_KEY, sessionId);
    updateSessionHint();

    setRunning(true);
    
    // 立即显示用户问题和"思考中"状态
    beginLiveRun(payload.goal);
    updateLiveProgress("任务已提交，准备连接后端流...");
    consoleSnapshotRunId = null;
    clearConsole();
    appendConsoleLine("USER", `问题：${payload.goal}`, "dim");
    setValue("goal", "");  // 立即清空输入框
    renderAll();

    // 然后发送请求到后端
    const resp = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/tasks`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        goal: payload.goal,
      }),
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
  } catch (error) {
    appendConsoleLine("ERROR", error.message, "err");
    if (liveRun) {
      liveRun.result.status = "error";
      liveRun.result.finalAnswer = `任务执行异常：${error.message}`;
      liveRun.result.durationMs = Math.max(0, Date.now() - currentRunStartMs);
      renderAll();
    }
  } finally {
    setRunning(false);
    renderAll();
  }
}

function handleStreamEvent(event) {
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
          `run_id: ${event.run_id || currentRunServerId || "-"}`,
          `approval_id: ${event.approval_id || "-"}`,
          `operation: ${(event.operation || {}).tool || "-"}.${(event.operation || {}).action || "-"}`,
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
        [`approval_id: ${event.approval_id || "-"}`, `decision: ${event.default_decision || "n"}`],
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

runBtn.addEventListener("click", runReact);

clearHistoryBtn.addEventListener("click", () => {
  localStorage.removeItem(SESSION_KEY);
  sessionSelectEl.value = "";
  activeRunId = null;
  activeStepKey = null;
  sessionRunItems = [];
  saveActiveRunId();
  updateSessionHint();
  renderAll();
});

clearConsoleBtn.addEventListener("click", () => {
  consoleSnapshotRunId = null;
  clearConsole();
});

if (createSessionBtn) {
  createSessionBtn.addEventListener("click", async () => {
    try {
      await createSession("", "");
      setValue("goal", "");
      sessionHintEl.textContent = "已创建新会话";
    } catch (_error) {
      sessionHintEl.textContent = "创建会话失败";
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
  activeRunId = sessionRunItems.length ? sessionRunItems[sessionRunItems.length - 1].id : activeRunId;
  renderAll();
});

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
  if (stepsPopoverEl) stepsPopoverEl.hidden = true;
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
  const popovers = [sessionPopoverEl, modelPopoverEl, stepsPopoverEl];
  const chips = [configChipModelEl, configChipStepsEl];
  
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

if (configChipStepsEl) {
  configChipStepsEl.addEventListener("click", () => {
    openPopover(stepsPopoverEl, configChipStepsEl);
    requestAnimationFrame(() => {
      maxStepsPopoverEl?.focus();
    });
  });
}

// Sync popover steps slider with input
if (maxStepsSliderEl && maxStepsPopoverEl) {
  maxStepsSliderEl.addEventListener("input", () => {
    const value = maxStepsSliderEl.value;
    if (maxStepsValueEl) maxStepsValueEl.textContent = value;
    maxStepsPopoverEl.value = value;
  });
}

if (maxStepsPopoverEl) {
  maxStepsPopoverEl.addEventListener("change", (e) => {
    const value = e.target.value;
    if (maxStepsSliderEl) maxStepsSliderEl.value = value;
    if (maxStepsValueEl) maxStepsValueEl.textContent = value;
    if (maxStepsEl) maxStepsEl.value = value;
    if (configChipStepsLabelEl) configChipStepsLabelEl.textContent = `步数: ${value}`;
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
      loadSessionTasks(selectedId).then(() => renderAll()).catch(() => renderAll());
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

for (const chip of goalChips) {
  chip.addEventListener("click", () => {
    setValue("goal", chip.dataset.goal || "");
  });
}

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
renderTabs();

checkHealth();
loadModelConfig();
loadMcpConfig();
loadSessions();
renderConfigCapsules();
renderAll();
