const runBtn = document.getElementById("runBtn");
const clearHistoryBtn = document.getElementById("clearHistoryBtn");
const summaryEl = document.getElementById("summary");
const timelineEl = document.getElementById("timeline");
const historyListEl = document.getElementById("historyList");
const healthBadgeEl = document.getElementById("healthBadge");
const stepTemplate = document.getElementById("stepTemplate");
const inspectorMetaEl = document.getElementById("inspectorMeta");
const inspectorOperationEl = document.getElementById("inspectorOperation");
const inspectorObservationEl = document.getElementById("inspectorObservation");
const copyOperationBtn = document.getElementById("copyOperationBtn");
const copyObservationBtn = document.getElementById("copyObservationBtn");
const clearConsoleBtn = document.getElementById("clearConsoleBtn");
const consoleLogEl = document.getElementById("consoleLog");
const liveStateEl = document.getElementById("liveState");
const liveStepEl = document.getElementById("liveStep");
const liveToolCallEl = document.getElementById("liveToolCall");
const liveElapsedEl = document.getElementById("liveElapsed");
const providerSelectEl = document.getElementById("providerSelect");
const modelSelectEl = document.getElementById("modelSelect");
const modelProfileHintEl = document.getElementById("modelProfileHint");
const currentModelTagEl = document.getElementById("currentModelTag");
const recentModelSwitchesEl = document.getElementById("recentModelSwitches");
const filterButtons = Array.from(document.querySelectorAll(".filter-btn"));
const inspectorModeButtons = Array.from(document.querySelectorAll(".tab-btn"));
const goalChips = Array.from(document.querySelectorAll(".chip"));

const HISTORY_KEY = "myclaw-agent-history-v1";
const PROVIDER_KEY = "myclaw-selected-provider";
const MODEL_KEY = "myclaw-selected-model";
const MODEL_SWITCHES_KEY = "myclaw-model-switches-v1";

let historyItems = loadHistory();
let activeRunId = historyItems.length ? historyItems[0].id : null;
let activeFilter = "all";
let activeStepKey = null;
let activeInspectorMode = "pretty";
let activeInspectorPayload = { operation: {}, observation: {} };
let isRunning = false;
let currentRunStartMs = 0;
let liveRun = null;
let modelConfig = { defaultProfileId: "", defaultModelId: "", providers: [] };
let recentModelSwitches = loadRecentModelSwitches();

function formatJson(value) {
  return activeInspectorMode === "raw" ? JSON.stringify(value) : JSON.stringify(value, null, 2);
}

function getValue(id) {
  return document.getElementById(id).value.trim();
}

function setValue(id, value) {
  document.getElementById(id).value = value;
}

function setRunning(running) {
  isRunning = running;
  runBtn.disabled = running;
  runBtn.textContent = running ? "运行中..." : "运行 Agent";
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
      steps: [],
    },
  };
  activeRunId = liveRun.id;
  activeStepKey = null;
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

function renderProviderAndModelSelectors() {
  providerSelectEl.innerHTML = "";
  modelSelectEl.innerHTML = "";
  const providers = Array.isArray(modelConfig.providers) ? modelConfig.providers : [];
  if (!providers.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "暂无模型配置，请先去模型配置页添加";
    providerSelectEl.appendChild(option);
    modelProfileHintEl.textContent = "未找到可用模型。";
    currentModelTagEl.textContent = "当前模型: -";
    return;
  }

  for (const provider of providers) {
    const option = document.createElement("option");
    option.value = provider.id;
    option.textContent = provider.name;
    providerSelectEl.appendChild(option);
  }

  const rememberedProvider = localStorage.getItem(PROVIDER_KEY);
  const providerIds = new Set(providers.map((item) => item.id));
  const selectedProviderId = providerIds.has(rememberedProvider)
    ? rememberedProvider
    : providerIds.has(modelConfig.defaultProfileId)
      ? modelConfig.defaultProfileId
      : providers[0].id;

  providerSelectEl.value = selectedProviderId;
  localStorage.setItem(PROVIDER_KEY, selectedProviderId);
  renderModelSelectorForProvider(selectedProviderId);
  updateModelProfileHint();
}

function renderModelSelectorForProvider(providerId) {
  modelSelectEl.innerHTML = "";
  const provider = (modelConfig.providers || []).find((item) => item.id === providerId);
  if (!provider || !Array.isArray(provider.models) || !provider.models.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "该 provider 暂无可用模型";
    modelSelectEl.appendChild(option);
    localStorage.setItem(MODEL_KEY, "");
    return;
  }

  for (const model of provider.models) {
    const option = document.createElement("option");
    option.value = model.id;
    option.textContent = `${model.name} (${model.model})`;
    modelSelectEl.appendChild(option);
  }

  const rememberedModel = localStorage.getItem(MODEL_KEY);
  const modelIds = new Set(provider.models.map((item) => item.id));
  const selectedModelId = modelIds.has(rememberedModel)
    ? rememberedModel
    : provider.id === modelConfig.defaultProfileId && modelIds.has(modelConfig.defaultModelId)
      ? modelConfig.defaultModelId
      : provider.models[0].id;
  modelSelectEl.value = selectedModelId;
  localStorage.setItem(MODEL_KEY, selectedModelId);
}

function updateModelProfileHint() {
  const selected = getSelectedProviderAndModel();
  if (!selected) {
    modelProfileHintEl.textContent = "请先在模型配置页添加模型。";
    currentModelTagEl.textContent = "当前模型: -";
    renderRecentModelSwitches();
    return;
  }
  modelProfileHintEl.textContent = `${selected.provider.baseUrl} · timeout=${selected.provider.timeout}s · ${selected.provider.jsonMode ? "JSON" : "TEXT"}`;
  currentModelTagEl.textContent = `当前模型: ${selected.provider.name} / ${selected.model.name} (${selected.model.model})`;
  renderRecentModelSwitches();
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

function renderSummary(runItem) {
  if (!runItem) {
    summaryEl.classList.add("empty");
    summaryEl.textContent = "等待执行。点击右侧开始后，这里会显示最终状态和摘要。";
    return;
  }

  const data = runItem.result;
  summaryEl.classList.remove("empty");
  summaryEl.innerHTML = `
    <div><strong>任务：</strong>${escapeHtml(runItem.goal)}</div>
    <div><strong>状态：</strong>${escapeHtml(data.status)}</div>
    <div><strong>耗时：</strong>${data.durationMs} ms</div>
    <div><strong>步骤数：</strong>${Array.isArray(data.steps) ? data.steps.length : 0}</div>
    <div><strong>最终回答：</strong>${escapeHtml(data.finalAnswer || "(空)")}</div>
  `;
}

function getActiveStep(runItem) {
  if (!runItem || !Array.isArray(runItem.result.steps) || !runItem.result.steps.length) {
    return null;
  }
  const filtered = filterSteps(runItem.result.steps);
  if (!filtered.length) {
    return null;
  }
  return filtered.find((step) => stepKey(step) === activeStepKey) || filtered[0];
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

function renderLiveStatus(runItem) {
  const activeStep = getActiveStep(runItem);

  let pillClass = "idle";
  let pillText = "IDLE";
  if (isRunning) {
    pillClass = "running";
    pillText = "RUNNING";
  } else if (runItem && runItem.result.status === "completed") {
    pillClass = "done";
    pillText = "DONE";
  } else if (runItem) {
    pillClass = "error";
    pillText = "ERROR";
  }
  liveStateEl.className = `live-pill ${pillClass}`;
  liveStateEl.textContent = pillText;

  liveStepEl.textContent = `当前 Step: ${activeStep ? activeStep.step : "-"}`;
  liveToolCallEl.textContent = `tool_call_id: ${getToolCallLabelFromStep(activeStep)}`;

  if (isRunning) {
    const elapsed = Math.max(0, Date.now() - currentRunStartMs);
    liveElapsedEl.textContent = `耗时: ${elapsed} ms`;
  } else if (runItem) {
    liveElapsedEl.textContent = `耗时: ${runItem.result.durationMs} ms`;
  } else {
    liveElapsedEl.textContent = "耗时: 0 ms";
  }
}

function stepOk(step) {
  if (step.observation) {
    return Boolean(step.observation.ok);
  }
  if (Array.isArray(step.observations)) {
    return step.observations.every((item) => Boolean(item.ok));
  }
  return false;
}

function filterSteps(steps) {
  if (activeFilter === "all") {
    return steps;
  }
  const expected = activeFilter === "ok";
  return steps.filter((step) => stepOk(step) === expected);
}

function stepKey(step) {
  return String(step.step);
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
  const data = normalizeInspectorData(step);
  activeInspectorPayload = {
    operation: data.operation,
    observation: data.observation,
  };
  inspectorMetaEl.textContent = data.metaText;
  inspectorMetaEl.classList.toggle("empty", data.empty);
  inspectorOperationEl.textContent = formatJson(data.operation);
  inspectorObservationEl.textContent = formatJson(data.observation);
}

function renderTimeline(runItem) {
  timelineEl.innerHTML = "";
  if (!runItem || !Array.isArray(runItem.result.steps) || runItem.result.steps.length === 0) {
    timelineEl.innerHTML = "<div class='step-card'>暂无可展示步骤。</div>";
    renderInspector(null);
    return;
  }

  const steps = filterSteps(runItem.result.steps);
  if (!steps.length) {
    timelineEl.innerHTML = "<div class='step-card'>当前筛选条件下没有步骤。</div>";
    renderInspector(null);
    return;
  }

  const availableKeys = new Set(steps.map(stepKey));
  if (!activeStepKey || !availableKeys.has(activeStepKey)) {
    activeStepKey = stepKey(steps[0]);
  }

  for (const step of steps) {
    const frag = stepTemplate.content.cloneNode(true);
    const card = frag.querySelector(".step-card");
    const meta = frag.querySelector(".step-meta");
    const pill = frag.querySelector(".pill");
    const pre = frag.querySelector("pre");

    const ok = stepOk(step);
    card.dataset.state = ok ? "ok" : "err";
    meta.textContent = `Step ${step.step} · ${step.operation ? step.operation.action : "batch"}`;
    pill.textContent = ok ? "SUCCESS" : "ERROR";
    pill.classList.add(ok ? "ok" : "err");
    pre.textContent = JSON.stringify(step, null, 2);

    const key = stepKey(step);
    card.classList.toggle("active", key === activeStepKey);
    card.addEventListener("click", () => {
      activeStepKey = key;
      renderAll();
    });

    timelineEl.appendChild(frag);
  }

  const activeStep = steps.find((step) => stepKey(step) === activeStepKey) || steps[0];
  renderInspector(activeStep);
}

function renderHistory() {
  historyListEl.innerHTML = "";
  if (!historyItems.length) {
    historyListEl.innerHTML = "<div class='history-item'><p>暂无历史记录</p></div>";
    return;
  }

  for (const item of historyItems) {
    const el = document.createElement("button");
    el.type = "button";
    el.className = "history-item";
    if (item.id === activeRunId) {
      el.classList.add("active");
    }
    el.innerHTML = `
      <p><strong>${escapeHtml(toRunTitle(item.goal))}</strong></p>
      <p class="history-meta">${escapeHtml(item.result.status)} · ${item.result.durationMs} ms</p>
    `;
    el.addEventListener("click", () => {
      activeRunId = item.id;
      renderAll();
    });
    historyListEl.appendChild(el);
  }
}

function renderAll() {
  const runItem = getCurrentRun();
  renderSummary(runItem);
  renderTimeline(runItem);
  renderLiveStatus(runItem);
  renderHistory();
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
  saveHistory();
  renderAll();
}

function collectPayload() {
  return {
    goal: getValue("goal"),
    providerId: providerSelectEl.value || "",
    modelId: modelSelectEl.value || "",
    maxSteps: Number(getValue("maxSteps") || "8"),
    approvalDecision: getValue("approvalDecision") || "1",
    mcpConfig: getValue("mcpConfig") || null,
    jsonMode: true,
  };
}

function validatePayload(payload) {
  if (!payload.goal) {
    throw new Error("请填写目标。");
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
    summaryEl.classList.remove("empty");
    summaryEl.textContent = error.message;
    return;
  }

  setRunning(true);
  beginLiveRun(payload.goal);
  clearConsole();
  appendConsoleLine("START", `目标：${payload.goal}`, "dim");
  renderAll();
  summaryEl.classList.remove("empty");
  summaryEl.textContent = "Agent 正在执行，请稍候...";

  try {
    const resp = await fetch("/api/run-react-stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
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
    summaryEl.classList.remove("empty");
    summaryEl.textContent = `执行失败: ${error.message}`;
    appendConsoleLine("ERROR", error.message, "err");
  } finally {
    setRunning(false);
    renderAll();
  }
}

function handleStreamEvent(event) {
  switch (event.type) {
    case "run_boot":
      appendConsoleBlock("BOOT", "开始任务", [`goal: ${event.goal}`], "dim");
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
      appendConsoleBlock(
        "CMD",
        toShellCommand(event.operation),
        summarizeOperation(event.operation),
        "dim",
      );
      break;
    case "approval":
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
      break;
    case "action_result": {
      const status = event.observation && event.observation.ok ? "ok" : "err";
      appendConsoleBlock(
        "OBS",
        status === "ok" ? "Tool result" : "Tool error",
        summarizeObservation(event.observation),
        status,
      );
      break;
    }
    case "step_complete":
      if (!liveRun) {
        beginLiveRun("unknown");
      }
      liveRun.result.steps.push(event.step_record);
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
      break;
    default:
      appendConsoleLine("INFO", summarizeObject(event), "dim");
      break;
  }
}

function setInspectorMode(mode) {
  activeInspectorMode = mode;
  for (const btn of inspectorModeButtons) {
    btn.classList.toggle("active", btn.dataset.mode === mode);
  }
  inspectorOperationEl.textContent = formatJson(activeInspectorPayload.operation || {});
  inspectorObservationEl.textContent = formatJson(activeInspectorPayload.observation || {});
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
    summaryEl.classList.remove("empty");
    summaryEl.textContent = "复制失败：当前环境可能不支持剪贴板权限。";
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

runBtn.addEventListener("click", runReact);

clearHistoryBtn.addEventListener("click", () => {
  historyItems = [];
  activeRunId = null;
  activeStepKey = null;
  saveHistory();
  renderAll();
});

clearConsoleBtn.addEventListener("click", () => {
  clearConsole();
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

for (const btn of filterButtons) {
  btn.addEventListener("click", () => {
    activeFilter = btn.dataset.filter || "all";
    for (const item of filterButtons) {
      item.classList.toggle("active", item === btn);
    }
    renderAll();
  });
}

for (const chip of goalChips) {
  chip.addEventListener("click", () => {
    setValue("goal", chip.dataset.goal || "");
  });
}

for (const btn of inspectorModeButtons) {
  btn.addEventListener("click", () => {
    setInspectorMode(btn.dataset.mode || "pretty");
  });
}

copyOperationBtn.addEventListener("click", () => {
  copyText(formatJson(activeInspectorPayload.operation || {}), copyOperationBtn);
});

copyObservationBtn.addEventListener("click", () => {
  copyText(formatJson(activeInspectorPayload.observation || {}), copyObservationBtn);
});

setInterval(() => {
  if (isRunning) {
    const runItem = getCurrentRun();
    renderLiveStatus(runItem);
  }
}, 200);

checkHealth();
loadModelConfig();
renderAll();
