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
    // fallback: 从 meta 文本中解析
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

  // ---- Render helpers ----

  function _matchRule(tool, action, rules) {
    // Returns the first matching rule or null
    for (const r of rules) {
      const toolMatch = r.tool === "*" || r.tool === tool;
      const actionMatch = r.action === "*" || r.action === action;
      if (toolMatch && actionMatch) return r;
    }
    return null;
  }

  function _renderToolTree(tools, globalRules, sessionRules) {
    if (!tools.length) {
      permToolTree.innerHTML = '<div class="perm-empty">暂无工具数据，请检查 MCP 配置</div>';
      return;
    }

    let html = "";
    for (const tool of tools) {
      const actions = tool.actions || [];
      const isCollapsed = false;
      const toolId = (tool.name || "unknown").replace(/[^a-zA-Z0-9_-]/g, "_");

      html += `<div class="perm-tool-group" data-tool="${toolId}">`;
      html += `<div class="perm-tool-group-head" data-toggle="${toolId}">`;
      html += `<span class="perm-toggle${isCollapsed ? " is-collapsed" : ""}">▼</span>`;
      html += `<span class="perm-tool-label">${_esc(tool.name || "未命名工具")}</span>`;
      if (tool.description) {
        html += `<span class="perm-tool-type">${_esc(tool.description.slice(0, 40))}${tool.description.length > 40 ? "…" : ""}</span>`;
      }
      html += `</div>`;

      // Actions list
      html += `<div class="perm-actions-list${isCollapsed ? " is-collapsed" : ""}" data-actions="${toolId}">`;
      for (const act of actions) {
        const actionName = act.name || act;
        const risk = act.risk || "low";

        // Check matching rules
        const gRule = _matchRule(tool.name, actionName, globalRules);
        const sRule = _matchRule(tool.name, actionName, sessionRules);

        let statusClass = "status-pending";
        let statusText = "待授权";
        let sourceText = "";

        if (gRule) {
          statusClass = gRule.effect === "deny" ? "status-deny" : "status-allow";
          statusText = gRule.effect === "deny" ? "拒绝" : "允许";
          sourceText = "全局规则";
        } else if (sRule) {
          statusClass = sRule.effect === "deny" ? "status-session-deny" : "status-session-allow";
          statusText = sRule.effect === "deny" ? "会话拒绝" : "会话允许";
          sourceText = "会话规则";
        }

        html += `<div class="perm-action-row">`;
        html += `<span class="perm-risk-dot risk-${risk}" title="风险: ${risk}"></span>`;
        html += `<span class="perm-action-name">${_esc(actionName)}</span>`;
        html += `<span class="perm-status-tag ${statusClass}">${statusText}</span>`;
        if (sourceText) {
          html += `<span class="perm-status-source">${sourceText}</span>`;
        }
        html += `</div>`;
      }
      html += `</div></div>`;
    }

    permToolTree.innerHTML = html;

    // Toggle collapse
    permToolTree.querySelectorAll(".perm-tool-group-head").forEach((head) => {
      head.addEventListener("click", () => {
        const toolId = head.dataset.toggle;
        const actions = permToolTree.querySelector(`[data-actions="${toolId}"]`);
        const toggle = head.querySelector(".perm-toggle");
        if (actions) actions.classList.toggle("is-collapsed");
        if (toggle) toggle.classList.toggle("is-collapsed");
      });
    });
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

    // Wire up buttons
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

    // Toggle session hint
    if (permNoSessionHint) {
      permNoSessionHint.style.display = sessionId ? "none" : "block";
    }
    if (permSessionRules) {
      permSessionRules.style.display = sessionId ? "flex" : "none";
    }

    // Fetch all data in parallel
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
      await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/policy/rules/${encodeURIComponent(ruleId)}`, { method: "DELETE" });
    } : null);
    permSessionRuleCount.textContent = String(sessionRules.length);

    _renderPending(pending, sessionId);
  }

  // ---- Expose globally ----
  window._permTabRefresh = _refresh;

  // Refresh button
  if (permRefreshBtn) {
    permRefreshBtn.addEventListener("click", _refresh);
  }

  // Auto-refresh when tab is shown
  document.querySelectorAll(".debug-tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.dataset.tab === "perm") {
        _refresh();
      }
    });
  });

  // Auto-refresh when session changes
  if (typeof window._onSessionChange === "undefined") {
    window._onSessionChange = [];
  }
  window._onSessionChange.push(_refresh);

})();