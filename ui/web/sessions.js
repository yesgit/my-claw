const archivedSessionListEl = document.getElementById("archivedSessionList");
const archivedSessionHintEl = document.getElementById("archivedSessionHint");
const refreshArchivedBtn = document.getElementById("refreshArchivedBtn");

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

function escapeHtml(input) {
  return String(input || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function fetchArchivedSessions() {
  const resp = await fetch("/api/sessions?limit=200&archivedOnly=true&includeRuntime=true");
  if (!resp.ok) {
    throw new Error("加载归档会话失败");
  }
  const data = await resp.json();
  return Array.isArray(data.sessions) ? data.sessions : [];
}

async function reviveSession(sessionId) {
  const resp = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/state`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ archived: false }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: "恢复会话失败" }));
    throw new Error(err.detail || "恢复会话失败");
  }
}

function renderArchivedSessions(items) {
  archivedSessionListEl.innerHTML = "";
  if (!items.length) {
    archivedSessionListEl.innerHTML = "<div class='session-settings-empty'>暂无归档会话。</div>";
    return;
  }

  for (const item of items) {
    const card = document.createElement("article");
    card.className = "session-settings-item";
    const sessionTypeLabel = String(item.session_type || "normal") === "schedule-runtime"
      ? "定时任务会话"
      : "普通会话";
    card.innerHTML = `
      <div class="session-settings-row">
        <div class="session-settings-name">${escapeHtml(item.name || "未命名会话")}</div>
        <button type="button" class="ghost-btn mini">复活</button>
      </div>
      <div class="session-settings-meta">${escapeHtml(sessionTypeLabel)} · 归档于 ${escapeHtml(formatIsoLike(item.archived_at))} · 更新于 ${escapeHtml(formatIsoLike(item.updated_at))} · 任务 ${escapeHtml(String(item.task_count || 0))}</div>
    `;

    const reviveBtn = card.querySelector("button");
    reviveBtn.addEventListener("click", async () => {
      reviveBtn.disabled = true;
      reviveBtn.textContent = "恢复中...";
      try {
        await reviveSession(item.id);
        archivedSessionHintEl.textContent = "会话已恢复，控制台会话列表将重新显示。";
        await loadArchivedSessions();
      } catch (_error) {
        reviveBtn.disabled = false;
        reviveBtn.textContent = "复活";
        archivedSessionHintEl.textContent = "恢复失败，请稍后重试。";
      }
    });

    archivedSessionListEl.appendChild(card);
  }
}

async function loadArchivedSessions() {
  archivedSessionHintEl.textContent = "正在加载归档会话...";
  try {
    const sessions = await fetchArchivedSessions();
    renderArchivedSessions(sessions);
    archivedSessionHintEl.textContent = sessions.length
      ? `共 ${sessions.length} 个归档会话。`
      : "当前没有归档会话。";
  } catch (_error) {
    archivedSessionListEl.innerHTML = "<div class='session-settings-empty'>加载失败，请重试。</div>";
    archivedSessionHintEl.textContent = "加载归档会话失败。";
  }
}

refreshArchivedBtn.addEventListener("click", () => {
  void loadArchivedSessions();
});

void loadArchivedSessions();
