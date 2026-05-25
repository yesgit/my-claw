/**
 * 权限 Tab — 策略模式 + 护栏 + 按操作视图 + 按资源视图
 */
(function () {
  "use strict";

  // ---- DOM refs ----
  const permToolTree = document.getElementById("permToolTree");
  const permGlobalRules = document.getElementById("permGlobalRules");
  const permGlobalRuleCount = document.getElementById("permGlobalRuleCount");
  const permRefreshBtn = document.getElementById("permRefreshBtn");
  const permModeSelector = document.getElementById("permModeSelector");
  const permModeDesc = document.getElementById("permModeDesc");
  const permViewOps = document.getElementById("permViewOps");
  const permViewResources = document.getElementById("permViewResources");
  const permResourceInput = document.getElementById("permResourceInput");
  const permResourceEffect = document.getElementById("permResourceEffect");
  const permResourceAddBtn = document.getElementById("permResourceAddBtn");
  const permResourceList = document.getElementById("permResourceList");
  const permRailHighRisk = document.getElementById("permRailHighRisk");
  const permRailFileModify = document.getElementById("permRailFileModify");
  const permRailShell = document.getElementById("permRailShell");

  // ---- State ----
  let _toolsCache = [];
  let _globalRulesCache = [];
  let _configCache = null;
  let _lastRefreshSessionId = "__never__";
  let _currentView = "ops";

  const MODE_DESCRIPTIONS = {
    strict: "严格模式：所有操作都需要审批",
    standard: "标准模式：读取自动放行，写入/执行需审批",
    permissive: "宽松模式：除黑名单外全部自动放行",
  };

  function _currentSessionId() {
    if (typeof window._getActiveSessionId === "function") {
      return window._getActiveSessionId() || null;
    }
    const meta = document.getElementById("sessionMetaInline");
    if (meta && meta.dataset.sessionId) return meta.dataset.sessionId;
    return null;
  }

  // ---- API helpers ----
  async function _fetchTools() {
    try {
      const sid = _currentSessionId();
      const url = sid ? `/api/tools?session_id=${encodeURIComponent(sid)}` : "/api/tools";
      const resp = await fetch(url);
      const data = await resp.json();
      return data.ok ? data.tools || [] : [];
    } catch { return []; }
  }

  async function _fetchGlobalRules() {
    try {
      const resp = await fetch("/api/policy/rules");
      const data = await resp.json();
      return data.ok ? data.rules || [] : [];
    } catch { return []; }
  }

  async function _fetchSessionRules(sessionId) {
    if (!sessionId) return [];
    try {
      const resp = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/policy/rules`);
      const data = await resp.json();
      return data.ok ? data.rules || [] : [];
    } catch { return []; }
  }

  async function _fetchPending() { return []; }

  async function _fetchConfig() {
    try {
      const resp = await fetch("/api/policy/config");
      const data = await resp.json();
      return data.ok ? data.config : null;
    } catch { return null; }
  }

  async function _updateConfig(updates) {
    try {
      const resp = await fetch("/api/policy/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updates),
      });
      const data = await resp.json();
      return data.ok ? data.config : null;
    } catch { return null; }
  }

  async function _createSessionRule(sessionId, tool, action, resource, effect) {
    try {
      await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/policy/rules`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tool, action, resource, effect }),
      });
    } catch { /* ignore */ }
  }

  async function _deleteSessionRule(sessionId, ruleId) {
    try {
      await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/policy/rules/${encodeURIComponent(ruleId)}`, {
        method: "DELETE",
      });
    } catch { /* ignore */ }
  }

  async function _createGlobalRule(tool, action, resource, effect, maxRisk) {
    try {
      const resp = await fetch("/api/policy/rules", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tool, action, resource, effect, max_risk: maxRisk || null }),
      });
      const data = await resp.json();
      return data.ok;
    } catch { return false; }
  }

  async function _deleteGlobalRule(ruleId) {
    try {
      const resp = await fetch(`/api/policy/rules/${encodeURIComponent(ruleId)}`, { method: "DELETE" });
      const data = await resp.json();
      return data.ok;
    } catch { return false; }
  }

  // ---- Helpers ----
  function _getToolName(tool) { return tool.tool || tool.tool_name || "unknown"; }
  function _getRisk(act) { return typeof act === "string" ? "low" : (act.default_risk || act.risk || "low"); }
  function _getActionName(act) { return typeof act === "string" ? act : (act.name || "unknown"); }

  function _matchRule(toolName, actionName, rules) {
    for (const r of rules) {
      const toolMatch = r.tool === "*" || r.tool === toolName;
      const actionMatch = r.action === "*" || r.action === actionName;
      if (toolMatch && actionMatch) return r;
    }
    return null;
  }

  function _esc(str) {
    const d = document.createElement("div");
    d.textContent = str || "";
    return d.innerHTML;
  }

  // ---- Render: Policy Mode ----
  function _renderConfig(config) {
    if (!config) return;
    const mode = config.mode || "standard";
    // Update mode buttons
    permModeSelector.querySelectorAll(".perm-mode-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.mode === mode);
    });
    permModeDesc.textContent = MODE_DESCRIPTIONS[mode] || "";

    const rails = config.safety_rails || {};
    if (permRailHighRisk) permRailHighRisk.checked = !!rails.high_risk_always_approve;
    if (permRailFileModify) permRailFileModify.checked = !!rails.file_modify_one_by_one;
    if (permRailShell) permRailShell.checked = !!rails.shell_one_by_one;
  }

  // ---- Render: Tool Tree (by operations) ----
  function _renderToolTree(tools, globalRules, sessionRules) {
    if (!tools.length) {
      permToolTree.innerHTML = '<div class="perm-empty">暂无工具数据，请检查 MCP 配置</div>';
      return;
    }

    const sessionId = _currentSessionId();
    const canAuth = !!sessionId;
    let html = "";

    for (const tool of tools) {
      const toolName = _getToolName(tool);
      const actions = tool.actions || [];
      const toolId = toolName.replace(/[^a-zA-Z0-9_-]/g, "_");
      const toolType = tool.type || "local";
      let displayLabel = toolName;
      if (toolType === "mcp" && tool.server) displayLabel = tool.mcp_tool_name || toolName;
      const desc = tool.description || "";

      html += `<div class="perm-tool-group" data-tool="${toolId}" data-tool-name="${_esc(toolName)}">`;
      html += `<div class="perm-tool-group-head" data-toggle="${toolId}">`;
      html += `<span class="perm-toggle">▼</span>`;
      html += `<span class="perm-tool-type-badge type-${toolType}">${_esc(toolType.toUpperCase())}</span>`;
      html += `<span class="perm-tool-label">${_esc(displayLabel)}</span>`;
      if (desc) {
        const shortDesc = desc.length > 40 ? desc.slice(0, 40) + "…" : desc;
        html += `<span class="perm-tool-desc" title="${_esc(desc)}">${_esc(shortDesc)}</span>`;
      }
      if (canAuth) {
        html += `<div class="perm-tool-batch">`;
        html += `<button class="perm-batch-btn perm-batch-allow" data-tool-name="${_esc(toolName)}" title="全部允许">✓ 全部允许</button>`;
        html += `<button class="perm-batch-btn perm-batch-deny" data-tool-name="${_esc(toolName)}" title="全部拒绝">✕ 全部拒绝</button>`;
        html += `</div>`;
      }
      html += `</div>`;

      html += `<div class="perm-actions-list" data-actions="${toolId}">`;
      for (const act of actions) {
        const actionName = _getActionName(act);
        const risk = _getRisk(act);
        const gRule = _matchRule(toolName, actionName, globalRules);
        const sRule = _matchRule(toolName, actionName, sessionRules);

        let statusClass = "status-pending";
        let statusText = "待授权";
        let sourceText = "";
        let matchedSessionRuleId = null;

        if (gRule) {
          statusClass = gRule.effect === "deny" ? "status-deny" : "status-allow";
          statusText = gRule.effect === "deny" ? "拒绝" : "允许";
          sourceText = "全局规则";
        } else if (sRule) {
          statusClass = sRule.effect === "deny" ? "status-session-deny" : "status-session-allow";
          statusText = sRule.effect === "deny" ? "会话拒绝" : "会话允许";
          sourceText = "会话规则";
          matchedSessionRuleId = sRule.id || null;
        }

        const resourcePattern = toolName === "mcp" && tool.server
          ? `mcp://${tool.server}/${actionName}/*`
          : `${toolName}://${actionName}`;

        html += `<div class="perm-action-row" data-tool-name="${_esc(toolName)}" data-action-name="${_esc(actionName)}" data-resource="${_esc(resourcePattern)}" data-session-rule-id="${matchedSessionRuleId || ""}">`;
        html += `<span class="perm-risk-dot risk-${risk}" title="风险: ${risk}"></span>`;
        html += `<span class="perm-action-name">${_esc(actionName)}</span>`;
        html += `<span class="perm-status-tag ${statusClass}">${statusText}</span>`;
        if (sourceText) html += `<span class="perm-status-source">${sourceText}</span>`;
        if (canAuth) {
          html += `<div class="perm-action-controls">`;
          if (matchedSessionRuleId) {
            html += `<button class="perm-ctrl-btn perm-ctrl-revoke" data-rule-id="${_esc(matchedSessionRuleId)}" title="撤销会话规则">撤销</button>`;
          }
          if (!gRule) {
            html += `<button class="perm-ctrl-btn perm-ctrl-allow" title="会话允许">✓</button>`;
            html += `<button class="perm-ctrl-btn perm-ctrl-deny" title="会话拒绝">✕</button>`;
          }
          html += `</div>`;
        }
        html += `</div>`;
      }
      html += `</div></div>`;
    }

    permToolTree.innerHTML = html;
    _wireToolTreeEvents(canAuth);
  }

  function _wireToolTreeEvents(canAuth) {
    permToolTree.querySelectorAll(".perm-tool-group-head").forEach((head) => {
      head.addEventListener("click", (e) => {
        if (e.target.closest(".perm-tool-batch")) return;
        const toolId = head.dataset.toggle;
        const actions = permToolTree.querySelector(`[data-actions="${toolId}"]`);
        const toggle = head.querySelector(".perm-toggle");
        if (actions) actions.classList.toggle("is-collapsed");
        if (toggle) toggle.classList.toggle("is-collapsed");
      });
    });

    if (!canAuth) return;

    permToolTree.querySelectorAll(".perm-batch-allow").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        await _batchSetToolAuth(btn.dataset.toolName, "allow");
      });
    });
    permToolTree.querySelectorAll(".perm-batch-deny").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        await _batchSetToolAuth(btn.dataset.toolName, "deny");
      });
    });
    permToolTree.querySelectorAll(".perm-ctrl-allow").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        await _setActionAuth(btn.closest(".perm-action-row"), "allow");
      });
    });
    permToolTree.querySelectorAll(".perm-ctrl-deny").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        await _setActionAuth(btn.closest(".perm-action-row"), "deny");
      });
    });
    permToolTree.querySelectorAll(".perm-ctrl-revoke").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        await _revokeActionAuth(btn.closest(".perm-action-row"));
      });
    });
  }

  async function _setActionAuth(row, effect) {
    const sid = _currentSessionId();
    if (!sid || !row) return;
    const existingRuleId = row.dataset.sessionRuleId;
    if (existingRuleId) await _deleteSessionRule(sid, existingRuleId);
    await _createSessionRule(sid, row.dataset.toolName, row.dataset.actionName, row.dataset.resource, effect);
    window._permTabRefresh(true);
  }

  async function _revokeActionAuth(row) {
    const sid = _currentSessionId();
    if (!sid || !row) return;
    const ruleId = row.dataset.sessionRuleId;
    if (ruleId) { await _deleteSessionRule(sid, ruleId); window._permTabRefresh(true); }
  }

  async function _batchSetToolAuth(toolName, effect) {
    const sid = _currentSessionId();
    if (!sid) return;
    const tool = _toolsCache.find((t) => _getToolName(t) === toolName);
    if (!tool) return;
    const sessionRules = await _fetchSessionRules(sid);
    const deletePromises = sessionRules.filter((r) => r.tool === toolName).map((r) => _deleteSessionRule(sid, r.id));
    await Promise.all(deletePromises);
    const actions = tool.actions || [];
    const createPromises = actions.map((act) => {
      const actionName = _getActionName(act);
      const resource = toolName === "mcp" && tool.server ? `mcp://${tool.server}/${actionName}/*` : `${toolName}://${actionName}`;
      return _createSessionRule(sid, toolName, actionName, resource, effect);
    });
    await Promise.all(createPromises);
    window._permTabRefresh(true);
  }

  // ---- Render: Resource View ----
  function _renderResourceView(globalRules) {
    const resourceRules = globalRules.filter((r) => r.resource && r.resource !== "*" && r.resource !== "/*");
    if (!resourceRules.length) {
      permResourceList.innerHTML = '<div class="perm-empty">暂无资源级规则，请通过上方输入框添加</div>';
      return;
    }

    let html = "";
    for (const r of resourceRules) {
      const effectClass = r.effect === "deny" ? "effect-deny" : "effect-allow";
      const effectText = r.effect === "deny" ? "DENY" : "ALLOW";
      html += `<div class="perm-resource-card" data-rule-id="${_esc(r.id)}">`;
      html += `<span class="perm-rule-effect ${effectClass}">${effectText}</span>`;
      html += `<span class="perm-resource-path" title="${_esc(r.resource)}">${_esc(r.resource)}</span>`;
      html += `<span class="perm-rule-meta">${_esc(r.tool)}/${_esc(r.action)}</span>`;
      html += `<button class="perm-rule-delete" data-rule-id="${_esc(r.id)}" title="删除">✕</button>`;
      html += `</div>`;
    }
    permResourceList.innerHTML = html;

    permResourceList.querySelectorAll(".perm-rule-delete").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (confirm("确定删除此规则？")) {
          await _deleteGlobalRule(btn.dataset.ruleId);
          window._permTabRefresh(true);
        }
      });
    });
  }

  // ---- Render: Rules List ----
  function _renderRulesList(container, rules, onDelete) {
    if (!rules.length) {
      container.innerHTML = '<div class="perm-empty">暂无规则</div>';
      return;
    }

    let html = "";
    for (const r of rules) {
      const effectClass = r.effect === "deny" ? "effect-deny" : "effect-allow";
      const effectText = r.effect === "deny" ? "DENY" : "ALLOW";
      const toolLabel = r.tool === "*" ? "所有工具" : r.tool;
      const actionLabel = r.action === "*" ? "所有动作" : r.action;
      const resourceLabel = (!r.resource || r.resource === "*" || r.resource === "/*") ? "所有资源" : r.resource;

      html += `<div class="perm-rule-card" data-rule-id="${_esc(r.id)}">`;
      html += `<span class="perm-rule-effect ${effectClass}">${effectText}</span>`;
      html += `<div class="perm-rule-detail">`;
      html += `<span class="perm-rule-tool">${_esc(toolLabel)}</span>`;
      html += `<span class="perm-rule-sep">/</span>`;
      html += `<span class="perm-rule-action">${_esc(actionLabel)}</span>`;
      html += `<span class="perm-rule-sep">/</span>`;
      html += `<span class="perm-rule-resource" title="${_esc(r.resource || "")}">${_esc(resourceLabel)}</span>`;
      if (r.max_risk) html += `<span class="perm-rule-max-risk">风险≤${_esc(r.max_risk)}</span>`;
      html += `</div>`;
      if (r.created_at) html += `<span class="perm-rule-meta">${_esc(r.created_at.slice(0, 16))}</span>`;
      if (onDelete) html += `<button class="perm-rule-delete" data-rule-id="${_esc(r.id)}" title="删除">✕</button>`;
      html += `</div>`;
    }

    container.innerHTML = html;

    if (onDelete) {
      container.querySelectorAll(".perm-rule-delete").forEach((btn) => {
        btn.addEventListener("click", async (e) => {
          e.stopPropagation();
          if (confirm("确定删除此规则？")) {
            await onDelete(btn.dataset.ruleId);
            window._permTabRefresh(true);
          }
        });
      });
    }
  }

  // ---- Main refresh ----
  async function _refresh(force = false) {
    const sessionId = _currentSessionId();
    if (!force && sessionId === _lastRefreshSessionId) return;
    _lastRefreshSessionId = sessionId;

    const [tools, globalRules, sessionRules, config] = await Promise.all([
      _fetchTools(),
      _fetchGlobalRules(),
      _fetchSessionRules(sessionId),
      _fetchConfig(),
    ]);

    _toolsCache = tools;
    _globalRulesCache = globalRules;
    _configCache = config;

    _renderConfig(config);
    _renderToolTree(tools, globalRules, sessionRules);
    _renderRulesList(permGlobalRules, globalRules, async (ruleId) => { await _deleteGlobalRule(ruleId); });
    permGlobalRuleCount.textContent = String(globalRules.length);
    _renderResourceView(globalRules);
  }

  // ---- Event wiring ----

  // Mode selector
  if (permModeSelector) {
    permModeSelector.addEventListener("click", async (e) => {
      const btn = e.target.closest(".perm-mode-btn");
      if (!btn) return;
      const mode = btn.dataset.mode;
      const config = await _updateConfig({ mode });
      if (config) _renderConfig(config);
    });
  }

  // Safety rails
  [permRailHighRisk, permRailFileModify, permRailShell].forEach((checkbox) => {
    if (!checkbox) return;
    checkbox.addEventListener("change", async () => {
      await _updateConfig({
        safety_rails: {
          high_risk_always_approve: permRailHighRisk ? permRailHighRisk.checked : true,
          file_modify_one_by_one: permRailFileModify ? permRailFileModify.checked : true,
          shell_one_by_one: permRailShell ? permRailShell.checked : false,
        },
      });
    });
  });

  // View switch
  document.querySelectorAll(".perm-view-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".perm-view-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      _currentView = btn.dataset.view;
      if (permViewOps) permViewOps.style.display = _currentView === "ops" ? "" : "none";
      if (permViewResources) permViewResources.style.display = _currentView === "resources" ? "" : "none";
    });
  });

  // Resource add
  if (permResourceAddBtn) {
    permResourceAddBtn.addEventListener("click", async () => {
      const resource = (permResourceInput.value || "").trim();
      if (!resource) return;
      const effectVal = permResourceEffect.value;
      let effect = "allow", action = "*", maxRisk = null;
      if (effectVal === "deny") { effect = "deny"; }
      else if (effectVal === "allow_read") { effect = "allow"; action = "read_*"; maxRisk = "low"; }

      await _createGlobalRule("*", action, resource, effect, maxRisk);
      permResourceInput.value = "";
      window._permTabRefresh(true);
    });
  }

  // Refresh button
  if (permRefreshBtn) permRefreshBtn.addEventListener("click", () => _refresh(true));

  // Tab activation
  document.querySelectorAll(".debug-tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => { if (btn.dataset.tab === "perm") _refresh(true); });
  });

  // Session change
  if (typeof window._onSessionChange === "undefined") window._onSessionChange = [];
  window._onSessionChange.push(_refresh);

  // Expose
  window._permTabRefresh = _refresh;
})();