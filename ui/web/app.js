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
const liveStateEl = document.getElementById("liveState");
const liveStepEl = document.getElementById("liveStep");
const liveToolCallEl = document.getElementById("liveToolCall");
const liveElapsedEl = document.getElementById("liveElapsed");
const filterButtons = Array.from(document.querySelectorAll(".filter-btn"));
const inspectorModeButtons = Array.from(document.querySelectorAll(".tab-btn"));
const goalChips = Array.from(document.querySelectorAll(".chip"));

const HISTORY_KEY = "myclaw-agent-history-v1";
let historyItems = loadHistory();
let activeRunId = historyItems.length ? historyItems[0].id : null;
let activeFilter = "all";
let activeStepKey = null;
let activeInspectorMode = "pretty";
let activeInspectorPayload = { operation: {}, observation: {} };
let isRunning = false;
let currentRunStartMs = 0;

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
  const runItem = getRunById(activeRunId);
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
  saveHistory();
  renderAll();
}

function collectPayload() {
  return {
    goal: getValue("goal"),
    llmBaseUrl: getValue("llmBaseUrl"),
    llmApiKey: getValue("llmApiKey"),
    llmModel: getValue("llmModel"),
    llmTimeout: 60,
    maxSteps: Number(getValue("maxSteps") || "8"),
    approvalDecision: getValue("approvalDecision") || "1",
    mcpConfig: getValue("mcpConfig") || null,
    jsonMode: true,
  };
}

function validatePayload(payload) {
  if (!payload.goal || !payload.llmBaseUrl || !payload.llmApiKey || !payload.llmModel) {
    throw new Error("请填写目标、LLM Base URL、API Key、模型名。")
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
  renderAll();
  summaryEl.classList.remove("empty");
  summaryEl.textContent = "Agent 正在执行，请稍候...";
  timelineEl.innerHTML = "";

  try {
    const resp = await fetch("/api/run-react", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: "请求失败" }));
      throw new Error(err.detail || "请求失败");
    }

    const result = await resp.json();
    pushRun(payload.goal, result);
  } catch (error) {
    summaryEl.classList.remove("empty");
    summaryEl.textContent = `执行失败: ${error.message}`;
  } finally {
    setRunning(false);
    renderAll();
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
    const runItem = getRunById(activeRunId);
    renderLiveStatus(runItem);
  }
}, 200);

checkHealth();
renderAll();
