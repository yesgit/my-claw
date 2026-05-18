/**
 * 权限 Tab — 工具权限树、持久规则、会话规则、待审批
 */
(function () {
  "use strict";

  // ---- DOM refs ----
  const permToolTree = document.getElementById("permToolTree");
  const permGlobalRules = document.getElementById("permGlobalRules");
  const permGlobalRuleCount = document.getElementById("permGlobalRuleCount");
  const permSessionRules = document.getElementById("permSessionRules");
  const permSessionRuleCount = document.getElementById("permSessionRuleCount");
  const permNoSessionHint = document.getElementById("permNoSessionHint");
  const permPendingList = document.getElementById("permPendingList");
  const permPendingCount = document.getElementById("permPendingCount");
  const permRefreshBtn = document.getElementById("permRefreshBtn");

  // ---- State ----
  let _toolsCache = [];
  let _globalRulesCache = [];
  let _sessionRulesCache = [];
  let _pendingCache = [];

  // 获取当前选中会话 ID（从 app.js 的全局状态）
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

  async function _fetchPending(sessionId) {
    if (!sessionId) return [];
    try {
      const resp = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/approvals/pending`);
      const data = await resp.json();
      return data.ok ? data.approvals || [] : [];
    } catch { return []; }
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

  // ---- Render helpers ----

  /**
   * 从工具描述中提取 tool identity。
   * 后端 describe() 返回 { tool, tool_name, type, actions, description, ... }
   */
  function _getToolName(tool) {
    return tool.tool || tool.tool_name || "unknown";
  }

  /**
   * 从 action 对象提取风险等级。
   * 后端返回 { name, default_risk } 或旧格式 { name, risk }
   */
  function _getRisk(act) {
    if (typeof act === "string") return "low";
    return act.default_risk || act.risk || "low";
  }

  /**
   * 从 action 对象提取名称。
   */
  function _getActionName(act) {
    return typeof act === "string" ? act : (act.name || "unknown");
  }

  function _matchRule(toolName, actionName, rules) {
    for (const r of rules) {
      const toolMatch = r.tool === "*" || r.tool === toolName;
      const actionMatch = r.action === "*" || r.action === actionName;
      if (toolMatch && actionMatch) return r;
    }
    return null;
  }

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
      const isCollapsed = false;
      const toolId = toolName.replace(/[^a-zA-Z0-9_-]/g, "_");
      const toolType = tool.type || "local";

      // Tool display label
      let displayLabel = toolName;
      if (toolType === "mcp" && tool.server) {
        displayLabel = tool.mcp_tool_name || toolName;
      }

      // Tool description
      const desc = tool.description || "";

      html += `<div class="perm-tool-group" data-tool="${toolId}" data-tool-name="${_esc(toolName)}">`;

      // ---- Tool group header ----
      html += `<div class="perm-tool-group-head" data-toggle="${toolId}">`;
      html += `<span class="perm-toggle${isCollapsed ? " is-collapsed" : ""}">▼</span>`;
      html += `<span class="perm-tool-type-badge type-${toolType}">${_esc(toolType.toUpperCase())}</span>`;
      html += `<span class="perm-tool-label">${_esc(displayLabel)}</span>`;
      if (desc) {
        const shortDesc = desc.length > 40 ? desc.slice(0, 40) + "…" : desc;
        html += `<span class="perm-tool-desc" title="${_esc(desc)}">${_esc(shortDesc)}</span>`;
      }
      // Batch authorization buttons (only when session is active)
      if (canAuth) {
        html += `<div class="perm-tool-batch">`;
        html += `<button class="perm-batch-btn perm-batch-allow" data-tool-name="${_esc(toolName)}" title="全部允许">✓ 全部允许</button>`;
        html += `<button class="perm-batch-btn perm-batch-deny" data-tool-name="${_esc(toolName)}" title="全部拒绝">✕ 全部拒绝</button>`;
        html += `</div>`;
      }
      html += `</div>`;

      // ---- Actions list ----
      html += `<div class="perm-actions-list${isCollapsed ? " is-collapsed" : ""}" data-actions="${toolId}">`;
      for (const act of actions) {
        const actionName = _getActionName(act);
        const risk = _getRisk(act);

        // Check matching rules
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

        // Resource pattern for rule creation
        const resourcePattern = toolName === "mcp" && tool.server
          ? `mcp://${tool.server}/${actionName}/*`
          : `${toolName}://${actionName}`;

        html += `<div class="perm-action-row" data-tool-name="${_esc(toolName)}" data-action-name="${_esc(actionName)}" data-resource="${_esc(resourcePattern)}" data-session-rule-id="${matchedSessionRuleId || ""}">`;
        html += `<span class="perm-risk-dot risk-${risk}" title="风险: ${risk}"></span>`;
        html += `<span class="perm-action-name">${_esc(actionName)}</span>`;
        html += `<span class="perm-status-tag ${statusClass}">${statusText}</span>`;
        if (sourceText) {
          html += `<span class="perm-status-source">${sourceText}</span>`;
        }
        // Authorization controls
        if (canAuth) {
          html += `<div class="perm-action-controls">`;
          if (matchedSessionRuleId) {
            // Has session rule → show revoke button
            html += `<button class="perm-ctrl-btn perm-ctrl-revoke" data-rule-id="${_esc(matchedSessionRuleId)}" title="撤销会话规则">撤销</button>`;
          }
          if (!gRule) {
            // Not blocked by global rule → can set session rule
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

    // ---- Wire up events ----

    // Toggle collapse (click on header but not on batch buttons)
    permToolTree.querySelectorAll(".perm-tool-group-head").forEach((head) => {
      head.addEventListener("click", (e) => {
        // Don't toggle if clicking batch buttons
        if (e.target.closest(".perm-tool-batch")) return;
        const toolId = head.dataset.toggle;
        const actions = permToolTree.querySelector(`[data-actions="${toolId}"]`);
        const toggle = head.querySelector(".perm-toggle");
        if (actions) actions.classList.toggle("is-collapsed");
        if (toggle) toggle.classList.toggle("is-collapsed");
      });
    });

    // Batch allow/deny
    if (canAuth) {
      permToolTree.querySelectorAll(".perm-batch-allow").forEach((btn) => {
        btn.addEventListener("click", async (e) => {
          e.stopPropagation();
          const toolName = btn.dataset.toolName;
          await _batchSetToolAuth(toolName, "allow");
        });
      });
      permToolTree.querySelectorAll(".perm-batch-deny").forEach((btn) => {
        btn.addEventListener("click", async (e) => {
          e.stopPropagation();
          const toolName = btn.dataset.toolName;
          await _batchSetToolAuth(toolName, "deny");
        });
      });

      // Action-level controls
      permToolTree.querySelectorAll(".perm-ctrl-allow").forEach((btn) => {
        btn.addEventListener("click", async (e) => {
          e.stopPropagation();
          const row = btn.closest(".perm-action-row");
          await _setActionAuth(row, "allow");
        });
      });
      permToolTree.querySelectorAll(".perm-ctrl-deny").forEach((btn) => {
        btn.addEventListener("click", async (e) => {
          e.stopPropagation();
          const row = btn.closest(".perm-action-row");
          await _setActionAuth(row, "deny");
        });
      });
      permToolTree.querySelectorAll(".perm-ctrl-revoke").forEach((btn) => {
        btn.addEventListener("click", async (e) => {
          e.stopPropagation();
          const row = btn.closest(".perm-action-row");
          await _revokeActionAuth(row);
        });
      });
    }
  }

  async function _setActionAuth(row, effect) {
    const sid = _currentSessionId();
    if (!sid || !row) return;
    const toolName = row.dataset.toolName;
    const actionName = row.dataset.actionName;
    const resource = row.dataset.resource;

    // If there's an existing session rule, delete it first
    const existingRuleId = row.dataset.sessionRuleId;
    if (existingRuleId) {
      await _deleteSessionRule(sid, existingRuleId);
    }

    await _createSessionRule(sid, toolName, actionName, resource, effect);
    window._permTabRefresh();
  }

  async function _revokeActionAuth(row) {
    const sid = _currentSessionId();
    if (!sid || !row) return;
    const ruleId = row.dataset.sessionRuleId;
    if (ruleId) {
      await _deleteSessionRule(sid, ruleId);
      window._permTabRefresh();
    }
  }

  async function _batchSetToolAuth(toolName, effect) {
    const sid = _currentSessionId();
    if (!sid) return;

    // Delete existing session rules for this tool's actions
    const deletePromises = _sessionRulesCache
      .filter((r) => r.tool === toolName)
      .map((r) => _deleteSessionRule(sid, r.id));
    await Promise.all(deletePromises);

    // Create new rules for all actions of this tool
    const tool = _toolsCache.find((t) => _getToolName(t) === toolName);
    if (!tool) return;

    const actions = tool.actions || [];
    const createPromises = actions.map((act) => {
      const actionName = _getActionName(act);
      const resource = toolName === "mcp" && tool.server
        ? `mcp://${tool.server}/${actionName}/*`
        : `${toolName}://${actionName}`;
      return _createSessionRule(sid, toolName, actionName, resource, effect);
    });
    await Promise.all(createPromises);
    window._permTabRefresh();
  }

  function _renderRulesList(container, rules, onDelete) {
    if (!rules.length) {
      container.innerHTML = '<div class="perm-empty">暂无规则</div>';
      return;
    }

    let html = "";
    for (const r of rules) {
      const pattern = `${r.tool} / ${r.action} / ${r.resource}`;
      const effectClass = r.effect === "deny" ? "effect-deny" : "effect-allow";
      const effectText = r.effect === "deny" ? "DENY" : "ALLOW";

      html += `<div class="perm-rule-card" data-rule-id="${_esc(r.id)}">`;
      html += `<span class="perm-rule-effect ${effectClass}">${effectText}</span>`;
      html += `<span class="perm-rule-pattern" title="${_esc(pattern)}">${_esc(pattern)}</span>`;
      if (r.created_at) {
        html += `<span class="perm-rule-meta">${_esc(r.created_at.slice(0, 16))}</span>`;
      }
      if (onDelete) {
        html += `<button class="perm-rule-delete" data-rule-id="${_esc(r.id)}" title="删除">✕</button>`;
      }
      html += `</div>`;
    }

    container.innerHTML = html;

    if (onDelete) {
      container.querySelectorAll(".perm-rule-delete").forEach((btn) => {
        btn.addEventListener("click", async (e) => {
          e.stopPropagation();
          const ruleId = btn.dataset.ruleId;
          if (ruleId && confirm("确定删除此规则？")) {
            await onDelete(ruleId);
            window._permTabRefresh();
          }
        });
      });
    }
  }

  function _renderPending(pending, sessionId) {
    if (!pending.length) {
      permPendingList.innerHTML = '<div class="perm-empty">无待审批项</div>';
      permPendingCount.textContent = "0";
      return;
    }

    permPendingCount.textContent = String(pending.length);

    let html = "";
    for (const p of pending) {
      const op = p.operation || {};
      const opText = `${op.tool || "?"} / ${op.action || "?"} / ${op.resource || "?"}`;
      html += `<div class="perm-pending-card">`;
      html += `<span class="perm-pending-op" title="${_esc(opText)}">${_esc(opText)}</span>`;
      html += `<div class="perm-pending-actions">`;
      html += `<button class="perm-approve-btn" data-run-id="${_esc(p.run_id)}" data-approval-id="${_esc(p.approval_id)}">允许</button>`;
      html += `<button class="perm-reject-btn" data-run-id="${_esc(p.run_id)}" data-approval-id="${_esc(p.approval_id)}">拒绝</button>`;
      html += `</div></div>`;
    }

    permPendingList.innerHTML = html;

    permPendingList.querySelectorAll(".perm-approve-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await _submitApproval(btn.dataset.runId, btn.dataset.approvalId, "1");
        window._permTabRefresh();
      });
    });
    permPendingList.querySelectorAll(".perm-reject-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await _submitApproval(btn.dataset.runId, btn.dataset.approvalId, "n");
        window._permTabRefresh();
      });
    });
  }

  async function _submitApproval(runId, approvalId, decision) {
    try {
      await fetch(`/api/runs/${encodeURIComponent(runId)}/approvals/${encodeURIComponent(approvalId)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision }),
      });
    } catch { /* ignore */ }
  }

  function _esc(str) {
    const d = document.createElement("div");
    d.textContent = str || "";
    return d.innerHTML;
  }

  // ---- Main refresh ----

  async function _refresh() {
    const sessionId = _currentSessionId();

    if (permNoSessionHint) {
      permNoSessionHint.style.display = sessionId ? "none" : "block";
    }
    if (permSessionRules) {
      permSessionRules.style.display = sessionId ? "flex" : "none";
    }

    const [tools, globalRules, sessionRules, pending] = await Promise.all([
      _fetchTools(),
      _fetchGlobalRules(),
      _fetchSessionRules(sessionId),
      _fetchPending(sessionId),
    ]);

    _toolsCache = tools;
    _globalRulesCache = globalRules;
    _sessionRulesCache = sessionRules;
    _pendingCache = pending;

    _renderToolTree(tools, globalRules, sessionRules);
    _renderRulesList(permGlobalRules, globalRules, null);
    permGlobalRuleCount.textContent = String(globalRules.length);

    _renderRulesList(permSessionRules, sessionRules, sessionId ? async (ruleId) => {
      await _deleteSessionRule(sessionId, ruleId);
    } : null);
    permSessionRuleCount.textContent = String(sessionRules.length);

    _renderPending(pending, sessionId);
  }

  // ---- Expose globally ----
  window._permTabRefresh = _refresh;

  if (permRefreshBtn) {
    permRefreshBtn.addEventListener("click", _refresh);
  }

  document.querySelectorAll(".debug-tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.dataset.tab === "perm") {
        _refresh();
      }
    });
  });

  if (typeof window._onSessionChange === "undefined") {
    window._onSessionChange = [];
  }
  window._onSessionChange.push(_refresh);

})();