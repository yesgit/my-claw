// ==================== 知识库管理页面逻辑 ====================

const API = "/api/knowledge";

// ==================== 侧栏导航切换 ====================
const navBtns = document.querySelectorAll(".kb-nav-btn[data-pane]");
const panes = document.querySelectorAll(".kb-pane");

navBtns.forEach((btn) => {
  btn.addEventListener("click", () => {
    navBtns.forEach((b) => b.classList.remove("active"));
    panes.forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    const target = btn.dataset.pane;
    const el = document.getElementById("pane" + target.charAt(0).toUpperCase() + target.slice(1));
    if (el) el.classList.add("active");
  });
});

// ==================== 工具函数 ====================
function showStatus(el, msg, type) {
  el.textContent = msg;
  el.className = "kb-status" + (type ? " " + type : "");
  el.style.display = "";
}

function clearStatus(el) {
  el.style.display = "none";
  el.textContent = "";
}

async function api(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body) opts.body = JSON.stringify(body);
  const resp = await fetch(API + path, opts);
  const data = await resp.json();
  if (!resp.ok) {
    throw new Error(data.detail || JSON.stringify(data));
  }
  return data;
}

// ==================== 文档列表 ====================
const docListEl = document.getElementById("docList");
const docCountEl = document.getElementById("docCount");

async function loadDocs() {
  try {
    const data = await api("GET", "/documents");
    const docs = data.documents || [];
    docCountEl.textContent = data.total || docs.length;

    if (docs.length === 0) {
      docListEl.innerHTML = '<div class="empty-tip">暂无文档，点击"+ 添加文本"开始</div>';
      return;
    }

    docListEl.innerHTML = docs
      .map(
        (d) => `
      <div class="doc-item">
        <div class="doc-head">
          <span class="doc-title">${escHtml(d.title)}</span>
          <button class="btn danger btn-del" data-id="${d.id}" type="button">删除</button>
        </div>
        <div class="doc-meta">
          <span>来源: ${escHtml(d.source_type)}</span>
          <span>字符数: ${d.char_count}</span>
          <span>分段数: ${d.chunk_count}</span>
          <span>创建: ${d.created_at}</span>
        </div>
        ${
          d.tags && d.tags.length
            ? '<div class="doc-tags">' + d.tags.map((t) => `<span class="doc-tag">${escHtml(t)}</span>`).join("") + "</div>"
            : ""
        }
      </div>`
      )
      .join("");

    // 绑定删除按钮
    docListEl.querySelectorAll(".btn-del").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!confirm("确认删除该文档？")) return;
        try {
          await api("DELETE", `/documents/${btn.dataset.id}`);
          loadDocs();
        } catch (e) {
          alert("删除失败: " + e.message);
        }
      });
    });
  } catch (e) {
    docListEl.innerHTML = `<div class="empty-tip">加载失败: ${escHtml(e.message)}</div>`;
  }
}

function escHtml(s) {
  const d = document.createElement("div");
  d.textContent = s || "";
  return d.innerHTML;
}

// ==================== 添加文本 ====================
const addTextBtn = document.getElementById("addTextBtn");
const addTextForm = document.getElementById("addTextForm");
const submitAddBtn = document.getElementById("submitAddBtn");
const cancelAddBtn = document.getElementById("cancelAddBtn");

addTextBtn.addEventListener("click", () => {
  addTextForm.style.display = addTextForm.style.display === "none" ? "" : "none";
});

cancelAddBtn.addEventListener("click", () => {
  addTextForm.style.display = "none";
});

submitAddBtn.addEventListener("click", async () => {
  const title = document.getElementById("addTitle").value.trim();
  const content = document.getElementById("addContent").value.trim();
  const tagsStr = document.getElementById("addTags").value.trim();

  if (!title) return alert("请输入标题");
  if (!content) return alert("请输入内容");

  const tags = tagsStr
    ? tagsStr
        .split(/[,，]/)
        .map((t) => t.trim())
        .filter(Boolean)
    : [];

  submitAddBtn.disabled = true;
  submitAddBtn.textContent = "提交中...";
  try {
    await api("POST", "/documents", { title, content, tags, source_type: "text" });
    document.getElementById("addTitle").value = "";
    document.getElementById("addContent").value = "";
    document.getElementById("addTags").value = "";
    addTextForm.style.display = "none";
    loadDocs();
  } catch (e) {
    alert("添加失败: " + e.message);
  } finally {
    submitAddBtn.disabled = false;
    submitAddBtn.textContent = "提交";
  }
});

// ==================== 刷新 & 重建索引 ====================
document.getElementById("refreshDocsBtn").addEventListener("click", loadDocs);

document.getElementById("rebuildIndexBtn").addEventListener("click", async () => {
  const btn = document.getElementById("rebuildIndexBtn");
  btn.disabled = true;
  btn.textContent = "重建中...";
  try {
    const data = await api("POST", "/rebuild-index");
    alert(`索引重建完成：FTS 索引 ${data.fts_count || 0} 条`);
  } catch (e) {
    alert("重建失败: " + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "重建索引";
  }
});

// ==================== 搜索测试 ====================
const searchBtn = document.getElementById("searchBtn");
const searchQueryEl = document.getElementById("searchQuery");
const searchStatusEl = document.getElementById("searchStatus");
const searchResultsEl = document.getElementById("searchResults");

searchBtn.addEventListener("click", doSearch);
searchQueryEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter") doSearch();
});

async function doSearch() {
  const query = searchQueryEl.value.trim();
  if (!query) return;

  showStatus(searchStatusEl, "搜索中...", "");
  searchResultsEl.innerHTML = "";

  try {
    const data = await api("POST", "/search", { query, top_k: 5 });
    const results = data.results || [];
    clearStatus(searchStatusEl);

    if (results.length === 0) {
      searchResultsEl.innerHTML = '<div class="empty-tip">无匹配结果</div>';
      return;
    }

    searchResultsEl.innerHTML = results
      .map(
        (r) => `
      <div class="search-result">
        <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
          <strong>${escHtml(r.doc_title || "未知文档")}</strong>
          <span class="score">分数: ${r.score}</span>
        </div>
        <div style="font-size:12px; color:var(--ink-soft); margin-bottom:4px;">
          文档ID: ${escHtml(r.document_id)} · 分段 #${r.chunk_index}
        </div>
        <div>${escHtml(r.snippet || r.content?.slice(0, 200))}</div>
      </div>`
      )
      .join("");
  } catch (e) {
    showStatus(searchStatusEl, "搜索失败: " + e.message, "err");
  }
}

// ==================== 嵌入模型配置 ====================
const embedStatusEl = document.getElementById("embedStatus");
const embedFields = {
  provider: document.getElementById("embedProvider"),
  model: document.getElementById("embedModel"),
  baseUrl: document.getElementById("embedBaseUrl"),
  apiKey: document.getElementById("embedApiKey"),
  dimension: document.getElementById("embedDimension"),
  timeout: document.getElementById("embedTimeout"),
};

async function loadEmbedConfig() {
  try {
    const data = await api("GET", "/embedding-config");
    const cfg = data.config || {};
    if (cfg.provider) embedFields.provider.value = cfg.provider;
    if (cfg.model) embedFields.model.value = cfg.model;
    if (cfg.baseUrl) embedFields.baseUrl.value = cfg.baseUrl;
    if (cfg.dimension) embedFields.dimension.value = cfg.dimension;
    if (cfg.timeout) embedFields.timeout.value = cfg.timeout;
    if (cfg.has_api_key) embedFields.apiKey.placeholder = "已保存（留空保持不变）";
  } catch (e) {
    // 首次加载无配置时忽略
  }
}

document.getElementById("saveEmbedBtn").addEventListener("click", async () => {
  const btn = document.getElementById("saveEmbedBtn");
  btn.disabled = true;
  btn.textContent = "保存中...";
  try {
    await api("POST", "/embedding-config", {
      provider: embedFields.provider.value,
      model: embedFields.model.value,
      baseUrl: embedFields.baseUrl.value,
      apiKey: embedFields.apiKey.value || undefined,
      dimension: parseInt(embedFields.dimension.value) || 1536,
      timeout: parseFloat(embedFields.timeout.value) || 30,
    });
    showStatus(embedStatusEl, "配置已保存", "ok");
    loadEmbedConfig();
  } catch (e) {
    showStatus(embedStatusEl, "保存失败: " + e.message, "err");
  } finally {
    btn.disabled = false;
    btn.textContent = "保存配置";
  }
});

document.getElementById("regenEmbedBtn").addEventListener("click", async () => {
  if (!confirm("确认重新生成所有文档的向量嵌入？这可能需要较长时间。")) return;
  const btn = document.getElementById("regenEmbedBtn");
  btn.disabled = true;
  btn.textContent = "生成中...";
  try {
    const data = await api("POST", "/rebuild-index");
    showStatus(embedStatusEl, `完成：FTS ${data.fts_count || 0} 条，向量 ${data.embed_count || 0} 条`, "ok");
  } catch (e) {
    showStatus(embedStatusEl, "失败: " + e.message, "err");
  } finally {
    btn.disabled = false;
    btn.textContent = "重新生成所有向量";
  }
});

// ==================== 初始化 ====================
loadDocs();
loadEmbedConfig();