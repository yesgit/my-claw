const pathEl = document.getElementById("mcpConfigPath");
const saveBtn = document.getElementById("saveMcpBtn");
const validateBtn = document.getElementById("validateMcpBtn");
const statusEl = document.getElementById("mcpStatus");
const serverListEl = document.getElementById("serverList");
const serverCountEl = document.getElementById("serverCount");

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

function renderServers(servers) {
  serverListEl.innerHTML = "";
  serverCountEl.textContent = String(servers.length);

  if (!servers.length) {
    serverListEl.innerHTML = "<div class='input-hint'>暂无 server 配置</div>";
    return;
  }

  for (const item of servers) {
    const div = document.createElement("div");
    div.className = "server-item";
    div.innerHTML = `
      <p><strong>${escapeHtml(item.name || "unknown")}</strong></p>
      <p class="server-meta">command: ${escapeHtml(Array.isArray(item.command) ? item.command.join(" ") : "")}</p>
      <p class="server-meta">cwd: ${escapeHtml(item.cwd || "-")}, envCount: ${escapeHtml(item.envCount || 0)}</p>
    `;
    serverListEl.appendChild(div);
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
    pathEl.value = config.defaultConfigPath || "";
    setStatus("配置已加载", "ok");
    await validateConfig();
  } catch (error) {
    setStatus(`加载失败: ${error.message}`, "err");
  }
}

async function saveConfig() {
  const payload = {
    defaultConfigPath: pathEl.value.trim(),
  };
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
    setStatus("配置已保存", "ok");
  } catch (error) {
    setStatus(`保存失败: ${error.message}`, "err");
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = "保存配置";
  }
}

async function validateConfig() {
  validateBtn.disabled = true;
  validateBtn.textContent = "校验中...";
  try {
    const resp = await fetch("/api/mcp-config/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ configPath: pathEl.value.trim() || null }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: "校验失败" }));
      throw new Error(err.detail || "校验失败");
    }
    const data = await resp.json();
    renderServers(data.servers || []);
    setStatus(`校验成功，共 ${data.count || 0} 个 server`, "ok");
  } catch (error) {
    renderServers([]);
    setStatus(`校验失败: ${error.message}`, "err");
  } finally {
    validateBtn.disabled = false;
    validateBtn.textContent = "校验并查看 Servers";
  }
}

saveBtn.addEventListener("click", saveConfig);
validateBtn.addEventListener("click", validateConfig);

loadConfig();
