const pathEl = document.getElementById("mcpConfigPath");
const saveBtn = document.getElementById("saveMcpBtn");
const validateBtn = document.getElementById("validateMcpBtn");
const addServerBtn = document.getElementById("addServerBtn");
const testAllBtn = document.getElementById("testAllBtn");
const statusEl = document.getElementById("mcpStatus");
const serverListEl = document.getElementById("serverList");
const serverCountEl = document.getElementById("serverCount");

let state = {
  defaultConfigPath: "",
  servers: [],
};

let serverTestResults = {};
const MAX_TEST_CONCURRENCY = 4;

function setStatus(text, tone = "") {
  statusEl.className = `mcp-status ${tone}`.trim();
  statusEl.textContent = text;
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function parseCommand(text) {
  const raw = String(text || "").trim();
  if (!raw) {
    return [];
  }
  const matched = raw.match(/(?:[^\s\"]+|\"[^\"]*\")+/g) || [];
  return matched.map((item) => item.replace(/^\"|\"$/g, "")).filter(Boolean);
}

function parseEnv(text) {
  const env = {};
  const lines = String(text || "").split("\n");
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      continue;
    }
    const idx = trimmed.indexOf("=");
    if (idx <= 0) {
      throw new Error(`环境变量格式错误: ${trimmed}`);
    }
    const key = trimmed.slice(0, idx).trim();
    const value = trimmed.slice(idx + 1).trim();
    if (!key) {
      throw new Error(`环境变量 key 不能为空: ${trimmed}`);
    }
    env[key] = value;
  }
  return env;
}

function toEnvText(env) {
  if (!env || typeof env !== "object") {
    return "";
  }
  return Object.entries(env)
    .map(([key, value]) => `${key}=${value}`)
    .join("\n");
}

function renderServers() {
  serverListEl.innerHTML = "";
  const list = Array.isArray(state.servers) ? state.servers : [];
  serverCountEl.textContent = String(list.length);

  if (!list.length) {
    serverListEl.innerHTML = "<div class='empty-tip'>暂无内嵌 server。你可以添加多个 server；若保持为空则使用兜底配置文件路径。</div>";
    return;
  }

  list.forEach((item, index) => {
    const div = document.createElement("article");
    div.className = "server-item";
    div.innerHTML = `
      <div class="server-head">
        <strong>Server ${index + 1}</strong>
        <button type="button" class="btn danger" data-remove-index="${index}">删除</button>
      </div>
      <div class="server-grid">
        <div>
          <label>名称</label>
          <input type="text" data-field="name" data-index="${index}" value="${escapeHtml(item.name || "")}" placeholder="例如: demo" />
        </div>
        <div>
          <label>工作目录 (cwd)</label>
          <input type="text" data-field="cwd" data-index="${index}" value="${escapeHtml(item.cwd || "")}" placeholder="例如: /root/projects/my-claw" />
        </div>
        <div class="full">
          <label>命令</label>
          <input type="text" data-field="commandText" data-index="${index}" value="${escapeHtml(Array.isArray(item.command) ? item.command.join(" ") : "")}" placeholder='例如: python -m backend.mcp.demo_server' />
          <p class="hint">支持带引号参数，例如: node server.js --name "my tool"</p>
        </div>
        <div class="full">
          <label>环境变量（每行 KEY=VALUE）</label>
          <textarea data-field="envText" data-index="${index}" placeholder="A=1&#10;B=2">${escapeHtml(toEnvText(item.env || {}))}</textarea>
        </div>
      </div>
      <div class="mcp-actions">
        <button type="button" class="btn" data-test-index="${index}">测试此 Server</button>
      </div>
      <p class="hint" data-test-result="${index}">${escapeHtml(serverTestResults[index] || "尚未测试")}</p>
    `;
    serverListEl.appendChild(div);
  });
}

function collectFromDom() {
  const nextServers = [];
  const names = new Set();

  const list = Array.from(serverListEl.querySelectorAll(".server-item"));
  list.forEach((item, index) => {
    const nameEl = item.querySelector('[data-field="name"]');
    const cwdEl = item.querySelector('[data-field="cwd"]');
    const commandEl = item.querySelector('[data-field="commandText"]');
    const envEl = item.querySelector('[data-field="envText"]');

    const name = String(nameEl?.value || "").trim();
    const cwd = String(cwdEl?.value || "").trim();
    const command = parseCommand(commandEl?.value || "");
    const env = parseEnv(envEl?.value || "");

    if (!name) {
      throw new Error(`第 ${index + 1} 个 server 缺少名称`);
    }
    if (!command.length) {
      throw new Error(`第 ${index + 1} 个 server 缺少命令`);
    }
    if (names.has(name)) {
      throw new Error(`server 名称重复: ${name}`);
    }

    names.add(name);
    nextServers.push({
      name,
      command,
      cwd: cwd || null,
      env,
    });
  });

  return {
    defaultConfigPath: String(pathEl.value || "").trim(),
    servers: nextServers,
  };
}

function bindServerEvents() {
  serverListEl.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    const testIndex = target.getAttribute("data-test-index");
    if (testIndex != null) {
      const idx = Number(testIndex);
      if (!Number.isNaN(idx)) {
        testSingleServer(idx, target);
      }
      return;
    }

    const removeIndex = target.getAttribute("data-remove-index");
    if (removeIndex != null) {
      const idx = Number(removeIndex);
      if (!Number.isNaN(idx)) {
        state.servers = state.servers.filter((_, i) => i !== idx);
        serverTestResults = {};
        renderServers();
      }
    }
  });
}

function collectServerFromItem(item, index) {
  const nameEl = item.querySelector('[data-field="name"]');
  const cwdEl = item.querySelector('[data-field="cwd"]');
  const commandEl = item.querySelector('[data-field="commandText"]');
  const envEl = item.querySelector('[data-field="envText"]');

  const name = String(nameEl?.value || "").trim();
  const cwd = String(cwdEl?.value || "").trim();
  const command = parseCommand(commandEl?.value || "");
  const env = parseEnv(envEl?.value || "");

  if (!name) {
    throw new Error(`第 ${index + 1} 个 server 缺少名称`);
  }
  if (!command.length) {
    throw new Error(`第 ${index + 1} 个 server 缺少命令`);
  }

  return {
    name,
    command,
    cwd: cwd || null,
    env,
  };
}

async function testServerPayload(server) {
  const resp = await fetch("/api/mcp-config/test-server", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ server }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: "测试失败" }));
    throw new Error(err.detail || "测试失败");
  }
  return resp.json();
}

async function testSingleServer(index, triggerBtn) {
  const cards = Array.from(serverListEl.querySelectorAll(".server-item"));
  const card = cards[index];
  if (!card) {
    return;
  }

  let server;
  try {
    server = collectServerFromItem(card, index);
  } catch (error) {
    serverTestResults[index] = `失败: ${error.message}`;
    renderServers();
    return;
  }

  if (triggerBtn instanceof HTMLButtonElement) {
    triggerBtn.disabled = true;
    triggerBtn.textContent = "测试中...";
  }

  try {
    const data = await testServerPayload(server);
    const protocol = data.protocolVersion ? `, protocol ${data.protocolVersion}` : "";
    serverTestResults[index] = `成功: ${data.latencyMs || 0} ms, tools ${data.toolCount || 0}${protocol}`;
    setStatus(`Server ${server.name} 测试成功`, "ok");
  } catch (error) {
    serverTestResults[index] = `失败: ${error.message}`;
    setStatus(`Server ${server.name} 测试失败`, "err");
  } finally {
    renderServers();
  }
}

async function testAllServers() {
  const saved = await saveConfig();
  if (!saved) {
    return;
  }

  if (!state.servers.length) {
    setStatus("没有可测试的 server", "err");
    return;
  }

  testAllBtn.disabled = true;
  testAllBtn.textContent = "测试中...";
  try {
    state.servers.forEach((_, index) => {
      serverTestResults[index] = "测试中...";
    });
    renderServers();

    const queue = state.servers.map((item, index) => ({ item, index }));
    const workerCount = Math.max(1, Math.min(MAX_TEST_CONCURRENCY, queue.length));

    async function worker() {
      const localResults = [];
      while (queue.length) {
        const next = queue.shift();
        if (!next) {
          break;
        }
        try {
          const data = await testServerPayload(next.item);
          const protocol = data.protocolVersion ? `, protocol ${data.protocolVersion}` : "";
          serverTestResults[next.index] = `成功: ${data.latencyMs || 0} ms, tools ${data.toolCount || 0}${protocol}`;
          localResults.push(true);
        } catch (error) {
          serverTestResults[next.index] = `失败: ${error.message}`;
          localResults.push(false);
        }
        renderServers();
      }
      return localResults;
    }

    const groupedResults = await Promise.all(Array.from({ length: workerCount }, () => worker()));
    const results = groupedResults.flat();
    const okCount = results.filter(Boolean).length;
    renderServers();
    setStatus(`测试完成：${okCount}/${state.servers.length} 成功`, okCount === state.servers.length ? "ok" : "err");
  } finally {
    testAllBtn.disabled = false;
    testAllBtn.textContent = "测试全部 Server";
  }
}

async function loadConfig() {
  setStatus("加载配置中...");
  try {
    const resp = await fetch("/api/mcp-config");
    if (!resp.ok) {
      throw new Error("加载失败");
    }
    const config = await resp.json();
    state = {
      defaultConfigPath: String(config.defaultConfigPath || ""),
      servers: Array.isArray(config.servers) ? config.servers : [],
    };
    pathEl.value = state.defaultConfigPath;
    renderServers();
    setStatus("配置已加载", "ok");
  } catch (error) {
    setStatus(`加载失败: ${error.message}`, "err");
  }
}

async function saveConfig() {
  let payload;
  try {
    payload = collectFromDom();
  } catch (error) {
    setStatus(`校验失败: ${error.message}`, "err");
    return false;
  }

  saveBtn.disabled = true;
  saveBtn.textContent = "保存中...";
  try {
    const resp = await fetch("/api/mcp-config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: "保存失败" }));
      throw new Error(err.detail || "保存失败");
    }
    state = payload;
    renderServers();
    setStatus(`配置已保存（${state.servers.length} 个 server）`, "ok");
    return true;
  } catch (error) {
    setStatus(`保存失败: ${error.message}`, "err");
    return false;
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = "保存配置";
  }
}

async function validateConfig() {
  const saved = await saveConfig();
  if (!saved) {
    return;
  }

  validateBtn.disabled = true;
  validateBtn.textContent = "校验中...";
  try {
    const resp = await fetch("/api/mcp-config/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ configPath: null }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: "校验失败" }));
      throw new Error(err.detail || "校验失败");
    }
    const data = await resp.json();
    const source = data.source === "file" ? "配置文件" : data.source === "inline" ? "内嵌配置" : "无";
    setStatus(`校验成功，共 ${data.count || 0} 个 server（来源: ${source}）`, "ok");
  } catch (error) {
    setStatus(`校验失败: ${error.message}`, "err");
  } finally {
    validateBtn.disabled = false;
    validateBtn.textContent = "校验配置";
  }
}

addServerBtn.addEventListener("click", () => {
  state.servers.push({
    name: "",
    command: [],
    cwd: null,
    env: {},
  });
  renderServers();
});

saveBtn.addEventListener("click", saveConfig);
validateBtn.addEventListener("click", validateConfig);
testAllBtn.addEventListener("click", testAllServers);
bindServerEvents();
loadConfig();
