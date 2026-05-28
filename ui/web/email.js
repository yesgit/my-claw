/**
 * MyClaw 邮箱配置页面逻辑
 */
(function () {
  "use strict";

  const API_BASE = "/api/email";
  const statusEl = document.getElementById("emailStatus");
  const listEl = document.getElementById("accountList");
  const countEl = document.getElementById("accountCount");

  function setStatus(msg, type) {
    statusEl.textContent = msg;
    statusEl.className = "email-status" + (type ? " " + type : "");
  }

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  async function apiGet(path) {
    const r = await fetch(API_BASE + path);
    return r.json();
  }

  async function apiRequest(method, path, body) {
    const opts = {
      method,
      headers: { "Content-Type": "application/json" },
    };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const r = await fetch(API_BASE + path, opts);
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || "请求失败");
    return data;
  }

  function createAccountEditor(account, isNew) {
    const div = document.createElement("div");
    div.className = "account-item";
    div.dataset.accountId = account.id || "";

    const enabled = account.enabled !== false;
    const badgeClass = enabled ? "badge-on" : "badge-off";
    const badgeText = enabled ? "已启用" : "已禁用";

    div.innerHTML = `
      <div class="account-head">
        <strong>${escapeHtml(account.name || account.email || "新账户")}</strong>
        <span>
          <span class="badge ${badgeClass}">${badgeText}</span>
        </span>
      </div>
      <div class="account-grid">
        <div>
          <label class="hint">账户名称</label>
          <input type="text" data-field="name" value="${escapeHtml(account.name || "")}" placeholder="如：工作邮箱" />
        </div>
        <div>
          <label class="hint">邮箱地址</label>
          <input type="email" data-field="email" value="${escapeHtml(account.email || "")}" placeholder="user@coremail.cn" />
        </div>
        <div>
          <label class="hint">IMAP 服务器</label>
          <input type="text" data-field="imap_host" value="${escapeHtml(account.imap_host || "")}" placeholder="imap.coremail.cn" />
        </div>
        <div>
          <label class="hint">IMAP 端口</label>
          <input type="number" data-field="imap_port" value="${account.imap_port || 993}" min="1" max="65535" />
        </div>
        <div>
          <label class="hint">SMTP 服务器（可选）</label>
          <input type="text" data-field="smtp_host" value="${escapeHtml(account.smtp_host || "")}" placeholder="smtp.coremail.cn" />
        </div>
        <div>
          <label class="hint">SMTP 端口</label>
          <input type="number" data-field="smtp_port" value="${account.smtp_port || 465}" min="1" max="65535" />
        </div>
        <div class="full">
          <label class="hint">${isNew ? "授权密码" : "授权密码（留空保持原值）"}</label>
          <input type="password" data-field="password" value="${isNew ? "" : "********"}" placeholder="IMAP 授权码" />
        </div>
        <div>
          <label class="toggle-label">
            <input type="checkbox" data-field="use_ssl" ${account.use_ssl !== false ? "checked" : ""} />
            使用 SSL/TLS
          </label>
        </div>
        <div>
          <label class="toggle-label">
            <input type="checkbox" data-field="enabled" ${enabled ? "checked" : ""} />
            启用监控
          </label>
        </div>
      </div>
      <div class="email-actions" style="margin-top:4px;">
        <button class="btn primary save-btn" type="button">${isNew ? "添加" : "保存"}</button>
        <button class="btn test-btn" type="button">测试连接</button>
        ${!isNew ? '<button class="btn danger delete-btn" type="button">删除</button>' : ""}
      </div>
    `;

    return div;
  }

  function collectFields(container) {
    const fields = {};
    container.querySelectorAll("[data-field]").forEach((el) => {
      const key = el.dataset.field;
      if (el.type === "checkbox") {
        fields[key] = el.checked;
      } else if (el.type === "number") {
        fields[key] = parseInt(el.value, 10) || 0;
      } else {
        fields[key] = el.value.trim();
      }
    });
    return fields;
  }

  async function loadAccounts() {
    try {
      const data = await apiGet("/accounts");
      const accounts = data.accounts || [];
      countEl.textContent = accounts.length;
      listEl.innerHTML = "";

      if (accounts.length === 0) {
        listEl.innerHTML = '<div class="empty-tip">尚未配置邮箱账户。点击「+ 添加账户」开始。</div>';
        setStatus("暂无账户", "");
        return;
      }

      accounts.forEach((acct) => {
        const el = createAccountEditor(acct, false);
        listEl.appendChild(el);
      });

      setStatus(`已加载 ${accounts.length} 个账户`, "ok");
    } catch (e) {
      setStatus("加载失败：" + e.message, "err");
    }
  }

  // ---- Event Delegation ----
  listEl.addEventListener("click", async (e) => {
    const btn = e.target.closest("button");
    if (!btn) return;
    const item = btn.closest(".account-item");
    if (!item) return;

    const accountId = item.dataset.accountId;

    if (btn.classList.contains("save-btn")) {
      const fields = collectFields(item);
      try {
        if (accountId) {
          // 清除占位密码
          if (fields.password === "********") delete fields.password;
          await apiRequest("PUT", `/accounts/${accountId}`, fields);
          setStatus("保存成功", "ok");
        } else {
          if (!fields.password) {
            setStatus("新账户必须填写授权密码", "err");
            return;
          }
          await apiRequest("POST", "/accounts", fields);
          setStatus("添加成功", "ok");
          loadAccounts();
        }
      } catch (e) {
        setStatus("操作失败：" + e.message, "err");
      }
    }

    if (btn.classList.contains("test-btn")) {
      const fields = collectFields(item);
      btn.disabled = true;
      btn.textContent = "测试中...";
      try {
        const body = accountId
          ? { account_id: accountId }
          : {
              imap_host: fields.imap_host,
              imap_port: fields.imap_port,
              email: fields.email,
              password: fields.password === "********" ? undefined : fields.password,
              use_ssl: fields.use_ssl,
            };
        const result = await apiRequest("POST", "/test-connection", body);
        setStatus(result.message || "连接成功", "ok");
      } catch (e) {
        setStatus("连接失败：" + e.message, "err");
      } finally {
        btn.disabled = false;
        btn.textContent = "测试连接";
      }
    }

    if (btn.classList.contains("delete-btn") && accountId) {
      if (!confirm("确定要删除此邮箱账户吗？")) return;
      try {
        await apiRequest("DELETE", `/accounts/${accountId}`);
        setStatus("已删除", "ok");
        loadAccounts();
      } catch (e) {
        setStatus("删除失败：" + e.message, "err");
      }
    }
  });

  // ---- Add New Account ----
  document.getElementById("addAccountBtn").addEventListener("click", () => {
    const el = createAccountEditor(
      {
        name: "",
        email: "",
        imap_host: "",
        imap_port: 993,
        smtp_host: "",
        smtp_port: 465,
        use_ssl: true,
        enabled: true,
      },
      true
    );
    listEl.prepend(el);
  });

  // ---- Init ----
  loadAccounts();
})();