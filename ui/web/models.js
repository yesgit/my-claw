// ===== DOM refs =====
const providersListEl = document.getElementById("providersList");
const statusEl = document.getElementById("status");
const formTitleEl = document.getElementById("formTitle");
const newProviderBtn = document.getElementById("newProviderBtn");
const deleteProviderBtn = document.getElementById("deleteProviderBtn");
const saveBtn = document.getElementById("saveBtn");
const testConnBtn = document.getElementById("testConnBtn");
const defaultProviderIdEl = document.getElementById("defaultProviderId");
const defaultModelIdEl = document.getElementById("defaultModelId");
const discoverBtn = document.getElementById("discoverBtn");
const discoverArea = document.getElementById("discoverArea");
const discoverApiKey = document.getElementById("discoverApiKey");
const doDiscoverBtn = document.getElementById("doDiscoverBtn");
const cancelDiscoverBtn = document.getElementById("cancelDiscoverBtn");
const discoverResults = document.getElementById("discoverResults");
const discoverModelList = document.getElementById("discoverModelList");
const discoverSelectAll = document.getElementById("discoverSelectAll");
const addDiscoveredBtn = document.getElementById("addDiscoveredBtn");
const modelListEl = document.getElementById("modelList");
const addModelBtn = document.getElementById("addModelBtn");

// Modal
const modelModal = document.getElementById("modelModal");
const modelModalTitle = document.getElementById("modelModalTitle");
const modalModelName = document.getElementById("modalModelName");
const modalModelId = document.getElementById("modalModelId");
const modalModelFlash = document.getElementById("modalModelFlash");
const modalModelVision = document.getElementById("modalModelVision");
const modalCancelBtn = document.getElementById("modalCancelBtn");
const modalConfirmBtn = document.getElementById("modalConfirmBtn");

// Preset Modal
const presetProviderBtn = document.getElementById("presetProviderBtn");
const presetModal = document.getElementById("presetModal");
const presetListEl = document.getElementById("presetList");
const presetCancelBtn = document.getElementById("presetCancelBtn");
const presetDetailModal = document.getElementById("presetDetailModal");
const presetDetailTitle = document.getElementById("presetDetailTitle");
const presetBaseUrlRow = document.getElementById("presetBaseUrlRow");
const presetBaseUrlSelect = document.getElementById("presetBaseUrlSelect");
const presetModelPreview = document.getElementById("presetModelPreview");
const presetDetailCancelBtn = document.getElementById("presetDetailCancelBtn");
const presetDetailConfirmBtn = document.getElementById("presetDetailConfirmBtn");

const providerNameEl = document.getElementById("providerName");
const providerBaseUrlEl = document.getElementById("providerBaseUrl");
const providerApiKeyEl = document.getElementById("providerApiKey");
const toggleApiKeyBtn = document.getElementById("toggleApiKeyBtn");
const apiKeyHintEl = document.getElementById("apiKeyHint");
const providerTimeoutEl = document.getElementById("providerTimeout");
const providerJsonModeEl = document.getElementById("providerJsonMode");
const providerProxyModeEl = document.getElementById("providerProxyMode");
const providerProxyUrlEl = document.getElementById("providerProxyUrl");
const providerProxyUrlRow = document.getElementById("providerProxyUrlRow");

// ===== State =====
let config = { defaultProviderId: "", defaultModelId: "", providers: [] };
let activeProviderId = "";
let editingModelId = null; // null = 添加模式, string = 编辑模式
let apiKeyRevealed = false; // API Key 是否处于明文显示状态
let apiKeyFullValue = "";   // 当前 provider 的完整 API Key 缓存
let apiKeyUserModified = false; // 用户是否手动修改了 API Key 字段

// ===== Helpers =====
function setStatus(text, tone = "") {
  if (!text) {
    statusEl.style.display = "none";
    return;
  }
  statusEl.style.display = "";
  statusEl.className = `status ${tone}`.trim();
  statusEl.textContent = text;
}

function getActiveProvider() {
  return config.providers.find((p) => p.id === activeProviderId) || null;
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ===== Render =====
function renderProviders() {
  providersListEl.innerHTML = "";
  if (!config.providers.length) {
    providersListEl.innerHTML = "<div class='provider-item'><p>暂无 provider，请新建</p></div>";
    return;
  }

  for (const provider of config.providers) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "provider-item";
    if (provider.id === activeProviderId) btn.classList.add("active");
    btn.innerHTML = `
      <p><strong>${escapeHtml(provider.name)}</strong></p>
      <p class="meta">${provider.models.length} 个模型</p>
    `;
    btn.addEventListener("click", () => {
      activeProviderId = provider.id;
      renderAll();
    });
    providersListEl.appendChild(btn);
  }
}

function renderDefaultSelectors() {
  // Default provider
  defaultProviderIdEl.innerHTML = "";
  for (const p of config.providers) {
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.textContent = p.name;
    defaultProviderIdEl.appendChild(opt);
  }
  if (config.providers.some((p) => p.id === config.defaultProviderId)) {
    defaultProviderIdEl.value = config.defaultProviderId;
  } else if (config.providers.length) {
    config.defaultProviderId = config.providers[0].id;
    defaultProviderIdEl.value = config.defaultProviderId;
  }

  // Default model
  defaultModelIdEl.innerHTML = "";
  const defProvider = config.providers.find((p) => p.id === config.defaultProviderId);
  if (defProvider && defProvider.models.length) {
    for (const m of defProvider.models) {
      const opt = document.createElement("option");
      opt.value = m.id;
      opt.textContent = `${m.name} (${m.model})`;
      defaultModelIdEl.appendChild(opt);
    }
    if (!defProvider.models.some((m) => m.id === config.defaultModelId)) {
      config.defaultModelId = defProvider.models[0].id;
    }
    defaultModelIdEl.value = config.defaultModelId;
  } else {
    defaultModelIdEl.innerHTML = "<option value=''>暂无模型</option>";
  }
}

function renderForm() {
  const provider = getActiveProvider();

  // 重置 API Key 显示状态
  apiKeyRevealed = false;
  apiKeyUserModified = false;
  apiKeyFullValue = "";
  providerApiKeyEl.type = "password";
  providerApiKeyEl.value = "";
  apiKeyHintEl.textContent = "";
  toggleApiKeyBtn.textContent = "👁";

  if (!provider) {
    providerNameEl.value = "";
    providerBaseUrlEl.value = "";
    providerTimeoutEl.value = "60";
    providerJsonModeEl.value = "true";
    renderModelList([]);
    formTitleEl.textContent = "Provider 详情（未选择）";
    return;
  }

  formTitleEl.textContent = `编辑: ${provider.name}`;
  providerNameEl.value = provider.name;
  providerBaseUrlEl.value = provider.baseUrl;
  providerTimeoutEl.value = String(provider.timeout || 60);
  providerJsonModeEl.value = provider.jsonMode ? "true" : "false";

  // 显示掩码后的 API Key（如果有）
  const masked = provider.apiKeyMasked || "";
  if (masked) {
    providerApiKeyEl.value = masked;
    apiKeyHintEl.textContent = "已保存，点击 👁 查看完整 Key";
  }

  // Proxy fields
  providerProxyModeEl.value = provider.proxyMode || "global";
  providerProxyUrlEl.value = provider.proxyUrl || "";
  updateProxyUrlVisibility();

  renderModelList(provider.models);
}

// ===== Proxy mode toggle =====
function updateProxyUrlVisibility() {
  providerProxyUrlRow.style.display = providerProxyModeEl.value === "custom" ? "" : "none";
}
providerProxyModeEl.addEventListener("change", updateProxyUrlVisibility);

// ===== API Key 显隐切换 =====
async function toggleApiKeyVisibility() {
  const provider = getActiveProvider();
  if (!provider) return;

  if (apiKeyRevealed) {
    // 切换回隐藏
    apiKeyRevealed = false;
    providerApiKeyEl.type = "password";
    providerApiKeyEl.value = provider.apiKeyMasked || apiKeyFullValue;
    toggleApiKeyBtn.textContent = "👁";
    apiKeyHintEl.textContent = provider.apiKeyMasked ? "已保存，点击 👁 查看完整 Key" : "";
    return;
  }

  // 从后端获取完整 Key
  try {
    const resp = await fetch(`/api/model-config/${encodeURIComponent(provider.id)}/reveal-key`);
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: "获取失败" }));
      setStatus(`获取 API Key 失败: ${err.detail || "未知错误"}`, "err");
      return;
    }
    const data = await resp.json();
    apiKeyFullValue = data.apiKey || "";
    apiKeyRevealed = true;
    providerApiKeyEl.type = "text";
    providerApiKeyEl.value = apiKeyFullValue;
    toggleApiKeyBtn.textContent = "🔒";
    apiKeyHintEl.textContent = apiKeyFullValue ? "正在显示完整 Key，编辑后保存即可更新" : "尚未设置 API Key";
  } catch (error) {
    setStatus(`获取 API Key 失败: ${error.message}`, "err");
  }
}

function renderModelList(models) {
  modelListEl.innerHTML = "";
  if (!models || !models.length) {
    modelListEl.innerHTML = "<div style='font-size:12px;color:var(--ink-soft);padding:8px;'>暂无模型，点击「添加模型」或「自动发现」</div>";
    return;
  }

  for (const model of models) {
    const div = document.createElement("div");
    div.className = "model-item";
    const flashBadge = model.flash ? '<span class="model-flash-badge" title="Flash 模型（摘要等简单任务优先使用）">⚡</span>' : '';
    const visionBadge = model.vision ? '<span class="model-vision-badge" title="视觉模型（支持图片/截图识别等多模态能力）">👁</span>' : '';
    div.innerHTML = `
      <span class="model-name">${flashBadge}${visionBadge}${escapeHtml(model.name)}</span>
      <span class="model-id">${escapeHtml(model.model)}</span>
      <div class="model-actions">
        <button class="model-btn edit" data-model-id="${escapeHtml(model.id)}" type="button">编辑</button>
        <button class="model-btn remove" data-model-id="${escapeHtml(model.id)}" type="button">✕</button>
      </div>
    `;
    div.querySelector(".model-btn.edit").addEventListener("click", () => {
      openModelModal(model);
    });
    div.querySelector(".model-btn.remove").addEventListener("click", () => {
      const provider = getActiveProvider();
      if (!provider) return;
      provider.models = provider.models.filter((m) => m.id !== model.id);
      renderModelList(provider.models);
      renderDefaultSelectors();
      setStatus(`已移除模型: ${model.name}`, "ok");
    });
    modelListEl.appendChild(div);
  }
}

function renderAll() {
  renderProviders();
  renderDefaultSelectors();
  renderForm();
}

// ===== Model Modal =====
function openModelModal(model = null) {
  if (model) {
    editingModelId = model.id;
    modelModalTitle.textContent = "编辑模型";
    modalModelName.value = model.name;
    modalModelId.value = model.model;
    modalModelFlash.checked = !!model.flash;
    modalModelVision.checked = !!model.vision;
  } else {
    editingModelId = null;
    modelModalTitle.textContent = "添加模型";
    modalModelName.value = "";
    modalModelId.value = "";
    modalModelFlash.checked = false;
    modalModelVision.checked = false;
  }
  modelModal.style.display = "flex";
  modalModelName.focus();
}

function closeModelModal() {
  modelModal.style.display = "none";
  editingModelId = null;
}

function confirmModel() {
  const provider = getActiveProvider();
  if (!provider) {
    setStatus("请先选择 provider", "err");
    return;
  }

  const name = modalModelName.value.trim();
  const modelId = modalModelId.value.trim();
  if (!name || !modelId) {
    setStatus("请填写模型名称和 ID", "err");
    return;
  }

  if (editingModelId) {
    // 编辑模式
    const flash = modalModelFlash.checked;
    const vision = modalModelVision.checked;
    const existing = provider.models.find((m) => m.id === editingModelId);
    if (existing) {
      existing.name = name;
      existing.model = modelId;
      existing.flash = flash;
      existing.vision = vision;
      // 如果 id 变了，更新 id
      if (editingModelId !== modelId) {
        // 检查新 id 是否冲突
        if (provider.models.some((m) => m.id === modelId && m.id !== editingModelId)) {
          setStatus(`模型 ID "${modelId}" 已存在`, "err");
          return;
        }
        existing.id = modelId;
      }
      setStatus(`已更新模型: ${name}`, "ok");
    }
  } else {
    // 添加模式
    if (provider.models.some((m) => m.id === modelId)) {
      setStatus(`模型 ID "${modelId}" 已存在`, "err");
      return;
    }
    provider.models.push({ id: modelId, name, model: modelId, flash: modalModelFlash.checked, vision: modalModelVision.checked });
    setStatus(`已添加模型: ${name}`, "ok");
  }

  renderModelList(provider.models);
  renderDefaultSelectors();
  closeModelModal();
}

// ===== Discover models =====
function showDiscover() {
  discoverArea.style.display = "block";
  discoverResults.style.display = "none";
  discoverApiKey.value = "";
}

function hideDiscover() {
  discoverArea.style.display = "none";
  discoverResults.style.display = "none";
  discoverModelList.innerHTML = "";
}

async function doDiscover() {
  const baseUrl = providerBaseUrlEl.value.trim();
  if (!baseUrl) {
    setStatus("请先填写 API 地址", "err");
    return;
  }

  const apiKey = discoverApiKey.value.trim();
  doDiscoverBtn.disabled = true;
  doDiscoverBtn.textContent = "发现中...";
  setStatus("正在自动发现模型...", "");

  try {
    const resp = await fetch("/api/model-config/discover", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        baseUrl,
        apiKey,
        proxyMode: providerProxyModeEl.value,
        proxyUrl: providerProxyModeEl.value === "custom" ? providerProxyUrlEl.value.trim() : "",
      }),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: "发现失败" }));
      throw new Error(err.detail || "发现失败");
    }

    const data = await resp.json();
    if (!data.models || !data.models.length) {
      setStatus("未发现任何模型", "err");
      return;
    }

    // 过滤掉已存在的模型
    const provider = getActiveProvider();
    const existingIds = new Set((provider?.models || []).map((m) => m.id));
    const newModels = data.models.filter((m) => !existingIds.has(m.id));

    if (!newModels.length) {
      setStatus("所有模型已存在，无需添加", "ok");
      return;
    }

    discoverModelList.innerHTML = "";
    for (const model of newModels) {
      const div = document.createElement("div");
      div.className = "discover-item";
      div.innerHTML = `
        <input type="checkbox" class="discover-checkbox" value="${escapeHtml(model.id)}" checked />
        <label>${escapeHtml(model.name)} <span style="color:var(--ink-soft);font-size:11px;">(${escapeHtml(model.model)})</span></label>
      `;
      discoverModelList.appendChild(div);
    }

    discoverResults.style.display = "grid";
    setStatus(`发现 ${newModels.length} 个新模型，请选择要添加的`, "ok");
  } catch (error) {
    setStatus(`发现失败: ${error.message}`, "err");
  } finally {
    doDiscoverBtn.disabled = false;
    doDiscoverBtn.textContent = "发现";
  }
}

function addDiscoveredModels() {
  const provider = getActiveProvider();
  if (!provider) return;

  const checkboxes = discoverModelList.querySelectorAll(".discover-checkbox:checked");
  const added = [];
  for (const cb of checkboxes) {
    const modelId = cb.value;
    const label = cb.closest(".discover-item").querySelector("label").textContent.trim();
    const model = { id: modelId, name: label.split("(")[0].trim(), model: modelId };
    if (!provider.models.some((m) => m.id === modelId)) {
      provider.models.push(model);
      added.push(model.name);
    }
  }

  if (added.length) {
    renderModelList(provider.models);
    renderDefaultSelectors();
    setStatus(`已添加 ${added.length} 个模型: ${added.join(", ")}`, "ok");
  } else {
    setStatus("未选择任何模型", "err");
  }
  hideDiscover();
}

// ===== Save =====
async function saveAll() {
  if (!config.providers.length) {
    setStatus("至少保留一个 provider", "err");
    return;
  }

  // 从表单同步当前 provider 的数据
  const provider = getActiveProvider();
  if (provider) {
    provider.name = providerNameEl.value.trim() || provider.name;
    provider.baseUrl = providerBaseUrlEl.value.trim() || provider.baseUrl;
    provider.timeout = Number(providerTimeoutEl.value || "60");
    provider.jsonMode = providerJsonModeEl.value === "true";
    provider.proxyMode = providerProxyModeEl.value;
    provider.proxyUrl = providerProxyModeEl.value === "custom" ? providerProxyUrlEl.value.trim() : "";
    // API Key 处理：
    // - 如果处于明文显示（已 reveal），直接用输入框的值
    // - 如果用户手动修改了字段（输入新 key），发送新值
    // - 否则不修改（不发送 apiKey，让后端保留原值）
    if (apiKeyRevealed || apiKeyUserModified) {
      provider.apiKey = providerApiKeyEl.value.trim();
    }
    // 清除 apiKeyMasked，后端不需要这个字段
    delete provider.apiKeyMasked;
  }

  config.defaultProviderId = defaultProviderIdEl.value || config.providers[0].id;
  config.defaultModelId = defaultModelIdEl.value || config.providers[0].models[0]?.id || "";

  try {
    const resp = await fetch("/api/model-config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: "保存失败" }));
      throw new Error(err.detail || "保存失败");
    }
    config = await resp.json();
    if (!config.providers.some((p) => p.id === activeProviderId)) {
      activeProviderId = config.defaultProviderId;
    }
    renderAll();
    setStatus("✅ 配置已保存", "ok");
  } catch (error) {
    setStatus(`保存失败: ${error.message}`, "err");
  }
}

// ===== Test connection =====
async function testConnection() {
  const provider = getActiveProvider();
  if (!provider) {
    setStatus("请先选择或创建一个 provider", "err");
    return;
  }

  const testModelId = defaultModelIdEl.value;
  const testModel = provider.models.find((m) => m.id === testModelId) || provider.models[0];
  if (!testModel) {
    setStatus("当前 provider 没有模型可测试", "err");
    return;
  }

  testConnBtn.disabled = true;
  testConnBtn.textContent = "测试中...";
  setStatus("正在测试连接...", "");

  try {
    const resp = await fetch("/api/model-config/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        providerId: provider.id,
        modelId: testModel.id,
        baseUrl: provider.baseUrl,
        model: testModel.model,
        apiKey: "",
        timeout: Number(providerTimeoutEl.value || "60"),
        jsonMode: providerJsonModeEl.value === "true",
      }),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: "连接测试失败" }));
      throw new Error(err.detail || "连接测试失败");
    }

    const result = await resp.json();
    setStatus(`✅ 连接成功 · ${result.model} · ${result.latencyMs}ms`, "ok");
  } catch (error) {
    setStatus(`❌ 连接失败: ${error.message}`, "err");
  } finally {
    testConnBtn.disabled = false;
    testConnBtn.textContent = "🔌 测试连接";
  }
}

// ===== CRUD =====
function createNewProvider() {
  const seed = Date.now().toString().slice(-6);
  const provider = {
    id: `provider-${seed}`,
    name: `新 Provider ${seed}`,
    baseUrl: "http://localhost:8000/v1",
    apiKey: "",
    timeout: 60,
    jsonMode: true,
    models: [],
  };
  config.providers.push(provider);
  activeProviderId = provider.id;
  if (!config.defaultProviderId) {
    config.defaultProviderId = provider.id;
  }
  renderAll();
  setStatus("已创建新 provider，请填写详细参数", "ok");
}

function deleteActiveProvider() {
  if (!activeProviderId) {
    setStatus("当前没有可删除的 provider", "err");
    return;
  }
  config.providers = config.providers.filter((p) => p.id !== activeProviderId);
  if (!config.providers.length) {
    activeProviderId = "";
    config.defaultProviderId = "";
    config.defaultModelId = "";
    renderAll();
    setStatus("已删除；请新建至少一个 provider", "err");
    return;
  }

  if (config.defaultProviderId === activeProviderId) {
    config.defaultProviderId = config.providers[0].id;
    config.defaultModelId = config.providers[0].models[0]?.id || "";
  }
  activeProviderId = config.providers[0].id;
  renderAll();
  setStatus("已删除 provider", "ok");
}

// ===== Load =====
async function loadConfig() {
  try {
    const resp = await fetch("/api/model-config");
    if (!resp.ok) throw new Error("加载失败");
    config = await resp.json();
    activeProviderId = config.defaultProviderId || config.providers[0]?.id || "";
    renderAll();
    setStatus("");
  } catch (error) {
    setStatus(`加载失败: ${error.message}`, "err");
  }
}

// ===== Events =====
newProviderBtn.addEventListener("click", createNewProvider);
deleteProviderBtn.addEventListener("click", deleteActiveProvider);
saveBtn.addEventListener("click", saveAll);
testConnBtn.addEventListener("click", testConnection);

// API Key 输入框变化追踪
providerApiKeyEl.addEventListener("input", () => {
  apiKeyUserModified = true;
});

// API Key 显隐切换按钮
toggleApiKeyBtn.addEventListener("click", toggleApiKeyVisibility);

addModelBtn.addEventListener("click", () => openModelModal(null));
discoverBtn.addEventListener("click", showDiscover);
cancelDiscoverBtn.addEventListener("click", hideDiscover);
doDiscoverBtn.addEventListener("click", doDiscover);
addDiscoveredBtn.addEventListener("click", addDiscoveredModels);

discoverSelectAll.addEventListener("change", () => {
  const checkboxes = discoverModelList.querySelectorAll(".discover-checkbox");
  for (const cb of checkboxes) cb.checked = discoverSelectAll.checked;
});

defaultProviderIdEl.addEventListener("change", () => {
  config.defaultProviderId = defaultProviderIdEl.value;
  renderDefaultSelectors();
  setStatus("默认 provider 已更新（未保存）", "ok");
});

defaultModelIdEl.addEventListener("change", () => {
  config.defaultModelId = defaultModelIdEl.value;
  setStatus("默认模型已更新（未保存）", "ok");
});

// Modal events
modalCancelBtn.addEventListener("click", closeModelModal);
modalConfirmBtn.addEventListener("click", confirmModel);
modelModal.addEventListener("click", (e) => {
  if (e.target === modelModal) closeModelModal();
});
modalModelId.addEventListener("keydown", (e) => {
  if (e.key === "Enter") confirmModel();
});
modalModelName.addEventListener("keydown", (e) => {
  if (e.key === "Enter") modalModelId.focus();
});

// ===== Preset Creation =====
let selectedPreset = null; // 当前选中的预设

function renderPresetList() {
  presetListEl.innerHTML = "";
  if (typeof PROVIDER_PRESETS === "undefined" || !PROVIDER_PRESETS.length) {
    presetListEl.innerHTML = "<p style='font-size:12px;color:var(--ink-soft);'>预设数据加载失败</p>";
    return;
  }

  for (const preset of PROVIDER_PRESETS) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.style.cssText = "border:1px solid var(--line);border-radius:12px;background:#fffef9;padding:10px 12px;cursor:pointer;text-align:left;width:100%;font:inherit;display:grid;gap:4px;";
    btn.innerHTML = `
      <p style="margin:0;font-size:13px;font-weight:500;">${escapeHtml(preset.name)}</p>
      <p style="margin:0;font-size:11px;color:var(--ink-soft);font-family:'Space Grotesk',monospace;">${escapeHtml(preset.baseUrls[0].url)}</p>
      <p style="margin:0;font-size:11px;color:var(--ink-soft);">${preset.suggestedModels.length} 个推荐模型${preset.baseUrls.length > 1 ? ' · ' + preset.baseUrls.length + ' 个端点' : ''}</p>
    `;
    btn.addEventListener("click", () => showPresetDetail(preset));
    btn.addEventListener("mouseenter", () => { btn.style.background = "#fff3e8"; });
    btn.addEventListener("mouseleave", () => { btn.style.background = "#fffef9"; });
    presetListEl.appendChild(btn);
  }
}

function showPresetDetail(preset) {
  selectedPreset = preset;
  presetDetailTitle.textContent = `创建: ${preset.name}`;

  // Render base URL selector
  presetBaseUrlSelect.innerHTML = "";
  for (const bu of preset.baseUrls) {
    const opt = document.createElement("option");
    opt.value = bu.url;
    opt.textContent = `${bu.label} — ${bu.url}`;
    presetBaseUrlSelect.appendChild(opt);
  }
  // Show/hide baseUrl row based on count
  presetBaseUrlRow.style.display = preset.baseUrls.length > 1 ? "" : "none";

  // Render model preview
  presetModelPreview.innerHTML = "";
  for (const m of preset.suggestedModels) {
    const div = document.createElement("div");
    div.style.cssText = "display:flex;align-items:center;gap:6px;padding:4px 6px;border:1px solid var(--line);border-radius:8px;font-size:12px;background:#fffef9;";
    const flashIcon = m.flash ? '⚡ ' : '';
    div.innerHTML = `
      <span style="flex:1;">${flashIcon}${escapeHtml(m.name)}</span>
      <span style="font-size:10px;color:var(--ink-soft);font-family:'Space Grotesk',monospace;">${escapeHtml(m.id)}</span>
    `;
    presetModelPreview.appendChild(div);
  }

  presetModal.style.display = "none";
  presetDetailModal.style.display = "flex";
}

function closePresetModal() {
  presetModal.style.display = "none";
  selectedPreset = null;
}

function closePresetDetailModal() {
  presetDetailModal.style.display = "none";
  selectedPreset = null;
}

function confirmPreset() {
  if (!selectedPreset) return;

  const seed = Date.now().toString().slice(-6);
  const baseUrl = selectedPreset.baseUrls.length > 1
    ? presetBaseUrlSelect.value
    : selectedPreset.baseUrls[0].url;

  // Check if a provider with this slug already exists, append seed if so
  const existingIds = new Set(config.providers.map((p) => p.id));
  let providerId = `preset-${selectedPreset.slug}`;
  if (existingIds.has(providerId)) {
    providerId = `preset-${selectedPreset.slug}-${seed}`;
  }

  const models = selectedPreset.suggestedModels.map((m) => ({
    id: m.id,
    name: m.name,
    model: m.id,
    flash: !!m.flash,
    vision: !!m.vision,
  }));

  const provider = {
    id: providerId,
    name: selectedPreset.name,
    baseUrl: baseUrl,
    apiKey: "",
    timeout: 60,
    jsonMode: true,
    models: models,
  };

  config.providers.push(provider);
  activeProviderId = provider.id;
  if (!config.defaultProviderId) {
    config.defaultProviderId = provider.id;
  }

  closePresetDetailModal();
  renderAll();
  setStatus(`已从预设创建「${selectedPreset.name}」${models.length} 个模型，请填写 API Key 后保存`, "ok");
}

// Preset events
presetProviderBtn.addEventListener("click", () => {
  renderPresetList();
  presetModal.style.display = "flex";
});
presetCancelBtn.addEventListener("click", closePresetModal);
presetModal.addEventListener("click", (e) => {
  if (e.target === presetModal) closePresetModal();
});

presetDetailCancelBtn.addEventListener("click", closePresetDetailModal);
presetDetailConfirmBtn.addEventListener("click", confirmPreset);
presetDetailModal.addEventListener("click", (e) => {
  if (e.target === presetDetailModal) closePresetDetailModal();
});

// ===== Init =====
loadConfig();
