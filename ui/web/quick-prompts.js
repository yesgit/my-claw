const QUICK_PROMPTS_KEY = "myclaw-quick-prompts-v1";

const labelInput = document.getElementById("qpLabel");
const goalInput = document.getElementById("qpGoal");
const addBtn = document.getElementById("btnAdd");
const listEl = document.getElementById("qpList");
const hintEl = document.getElementById("qpHint");
const toastEl = document.getElementById("toast");

function loadPrompts() {
  try {
    const raw = localStorage.getItem(QUICK_PROMPTS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch (_error) {
    return [];
  }
}

function savePrompts(prompts) {
  localStorage.setItem(QUICK_PROMPTS_KEY, JSON.stringify(prompts));
}

function showToast(text, duration = 1800) {
  toastEl.textContent = text;
  toastEl.classList.add("show");
  setTimeout(() => toastEl.classList.remove("show"), duration);
}

function escapeHtml(text) {
  const el = document.createElement("span");
  el.textContent = String(text);
  return el.innerHTML;
}

function renderList() {
  const prompts = loadPrompts();
  listEl.innerHTML = "";

  if (!prompts.length) {
    listEl.innerHTML = '<li class="qp-empty">暂未配置快捷提问，请在上方添加。</li>';
    hintEl.textContent = "";
    return;
  }

  hintEl.textContent = `共 ${prompts.length} 条`;

  prompts.forEach((item, idx) => {
    const li = document.createElement("li");
    li.className = "qp-item";
    li.innerHTML = `
      <span class="qp-item-label" title="${escapeHtml(item.label || "")}">${escapeHtml(item.label || "")}</span>
      <span class="qp-item-goal" title="${escapeHtml(item.goal || "")}">${escapeHtml(item.goal || "")}</span>
      <div class="qp-item-actions">
        <button type="button" class="qp-item-btn" data-action="up" ${idx === 0 ? "disabled" : ""} title="上移">↑</button>
        <button type="button" class="qp-item-btn" data-action="down" ${idx === prompts.length - 1 ? "disabled" : ""} title="下移">↓</button>
        <button type="button" class="qp-item-btn danger" data-action="delete" title="删除">✕</button>
      </div>
    `;

    li.querySelector('[data-action="up"]')?.addEventListener("click", () => {
      const list = loadPrompts();
      if (idx > 0) {
        [list[idx - 1], list[idx]] = [list[idx], list[idx - 1]];
        savePrompts(list);
        renderList();
      }
    });

    li.querySelector('[data-action="down"]')?.addEventListener("click", () => {
      const list = loadPrompts();
      if (idx < list.length - 1) {
        [list[idx], list[idx + 1]] = [list[idx + 1], list[idx]];
        savePrompts(list);
        renderList();
      }
    });

    li.querySelector('[data-action="delete"]')?.addEventListener("click", () => {
      const list = loadPrompts();
      list.splice(idx, 1);
      savePrompts(list);
      renderList();
      showToast("已删除");
    });

    listEl.appendChild(li);
  });
}

addBtn.addEventListener("click", () => {
  const label = String(labelInput.value || "").trim();
  const goal = String(goalInput.value || "").trim();

  if (!label) {
    hintEl.textContent = "请输入按钮标签";
    labelInput.focus();
    return;
  }
  if (!goal) {
    hintEl.textContent = "请输入提示词内容";
    goalInput.focus();
    return;
  }

  const prompts = loadPrompts();
  prompts.push({ label, goal });
  savePrompts(prompts);

  labelInput.value = "";
  goalInput.value = "";
  hintEl.textContent = "";
  renderList();
  showToast("已添加");
});

renderList();