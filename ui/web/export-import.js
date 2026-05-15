(function () {
  "use strict";

  // ===== 嵌入 iframe 时隐藏顶部导航 =====
  const params = new URLSearchParams(window.location.search);
  if (params.get("embedded") === "1") {
    const header = document.querySelector(".embedded-hide");
    if (header) header.remove();
  }

  // ===== DOM 引用 =====
  const exportModelsCb = document.getElementById("exportModels");
  const exportMcpCb = document.getElementById("exportMcp");
  const btnExport = document.getElementById("btnExport");
  const btnPreviewExport = document.getElementById("btnPreviewExport");
  const exportPreview = document.getElementById("exportPreview");
  const exportPreviewText = document.getElementById("exportPreviewText");

  const btnChooseFile = document.getElementById("btnChooseFile");
  const importFileInput = document.getElementById("importFileInput");
  const selectedFileName = document.getElementById("selectedFileName");
  const importFileSummary = document.getElementById("importFileSummary");
  const importOptions = document.getElementById("importOptions");
  const importModelsCb = document.getElementById("importModels");
  const importMcpCb = document.getElementById("importMcp");
  const btnImport = document.getElementById("btnImport");
  const importResult = document.getElementById("importResult");

  const toastEl = document.getElementById("toast");

  let importedPayload = null;

  // ===== 工具函数 =====

  function showToast(msg, isError) {
    toastEl.textContent = msg;
    toastEl.classList.toggle("error", !!isError);
    toastEl.classList.add("show");
    clearTimeout(showToast._timer);
    showToast._timer = setTimeout(function () {
      toastEl.classList.remove("show");
    }, 2800);
  }

  function apiPost(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(function (resp) {
      return resp.json().then(function (data) {
        if (!resp.ok) {
          throw new Error(data.detail || "请求失败");
        }
        return data;
      });
    });
  }

  function downloadJson(data, filename) {
    var blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  // ===== 导出 =====

  function getExportParams() {
    return {
      exportModels: exportModelsCb.checked,
      exportMcp: exportMcpCb.checked,
    };
  }

  btnExport.addEventListener("click", function () {
    var params = getExportParams();
    if (!params.exportModels && !params.exportMcp) {
      showToast("请至少选择一个导出模块", true);
      return;
    }

    btnExport.disabled = true;
    apiPost("/api/config/export", params)
      .then(function (resp) {
        var data = resp.data;
        var ts = new Date().toISOString().slice(0, 10);
        downloadJson(data, "myclaw-config-" + ts + ".json");
        showToast("配置已导出并下载");
      })
      .catch(function (err) {
        showToast("导出失败: " + err.message, true);
      })
      .finally(function () {
        btnExport.disabled = false;
      });
  });

  btnPreviewExport.addEventListener("click", function () {
    var params = getExportParams();
    if (!params.exportModels && !params.exportMcp) {
      showToast("请至少选择一个导出模块", true);
      return;
    }

    btnPreviewExport.disabled = true;
    apiPost("/api/config/export", params)
      .then(function (resp) {
        exportPreviewText.textContent = JSON.stringify(resp.data, null, 2);
        exportPreview.style.display = "";
      })
      .catch(function (err) {
        showToast("预览失败: " + err.message, true);
      })
      .finally(function () {
        btnPreviewExport.disabled = false;
      });
  });

  // ===== 导入 =====

  btnChooseFile.addEventListener("click", function () {
    importFileInput.click();
  });

  importFileInput.addEventListener("change", function () {
    var file = importFileInput.files[0];
    if (!file) {
      selectedFileName.textContent = "未选择文件";
      importedPayload = null;
      importOptions.style.display = "none";
      importFileSummary.style.display = "none";
      return;
    }

    selectedFileName.textContent = file.name;

    var reader = new FileReader();
    reader.onload = function (e) {
      try {
        var data = JSON.parse(e.target.result);
      } catch (parseErr) {
        showToast("文件不是有效的 JSON: " + parseErr.message, true);
        importedPayload = null;
        importOptions.style.display = "none";
        importFileSummary.style.display = "none";
        return;
      }

      if (!data.version) {
        showToast("不是有效的 MyClaw 配置文件（缺少 version 字段）", true);
        importedPayload = null;
        importOptions.style.display = "none";
        importFileSummary.style.display = "none";
        return;
      }

      importedPayload = data;

      // 显示文件摘要
      var summaryParts = [];
      summaryParts.push("版本: " + (data.version || "未知"));
      if (data.exportedAt) {
        summaryParts.push("导出时间: " + data.exportedAt);
      }
      if (data.models) {
        var providerCount = (data.models.providers || []).length;
        summaryParts.push("模型配置: " + providerCount + " 个 provider");
        // 默认勾选
        importModelsCb.checked = true;
      } else {
        importModelsCb.checked = false;
        importModelsCb.disabled = true;
        summaryParts.push("模型配置: 无");
      }
      if (data.mcp) {
        var serverCount = (data.mcp.servers || []).length;
        summaryParts.push("MCP 配置: " + serverCount + " 个 server");
        importMcpCb.checked = true;
      } else {
        importMcpCb.checked = false;
        importMcpCb.disabled = true;
        summaryParts.push("MCP 配置: 无");
      }

      importFileSummary.innerHTML = "<strong>文件内容摘要：</strong><br/>" + summaryParts.join("<br/>");
      importFileSummary.style.display = "";

      // 如果有可导入的模块，显示选项
      var hasImportable = data.models || data.mcp;
      importOptions.style.display = hasImportable ? "" : "none";

      // 重置导入结果
      importResult.classList.remove("show");
      importResult.textContent = "";
    };
    reader.readAsText(file);
  });

  btnImport.addEventListener("click", function () {
    if (!importedPayload) {
      showToast("请先选择配置文件", true);
      return;
    }

    var importModels = importModelsCb.checked;
    var importMcp = importMcpCb.checked;

    if (!importModels && !importMcp) {
      showToast("请至少选择一个导入模块", true);
      return;
    }

    if (!confirm("导入将覆盖当前所选模块的配置，确认继续？")) {
      return;
    }

    btnImport.disabled = true;
    importResult.classList.remove("show");

    apiPost("/api/config/import", {
      payload: importedPayload,
      importModels: importModels,
      importMcp: importMcp,
    })
      .then(function (resp) {
        var imported = resp.imported || [];
        var lines = ["✅ 导入完成"];
        if (imported.length === 0) {
          lines = ["⚠️ 未导入任何模块"];
        } else {
          if (imported.indexOf("models") >= 0) {
            lines.push("模型配置已导入");
          }
          if (imported.indexOf("mcp") >= 0) {
            lines.push("MCP 配置已导入");
          }
        }
        importResult.textContent = lines.join("\n");
        importResult.classList.add("show");
        showToast("配置导入成功");
      })
      .catch(function (err) {
        importResult.textContent = "❌ 导入失败: " + err.message;
        importResult.classList.add("show");
        showToast("导入失败: " + err.message, true);
      })
      .finally(function () {
        btnImport.disabled = false;
      });
  });
})();