const safeWorksheetId = (value: string): string =>
  String(value || "worksheet")
    .replace(/[^a-zA-Z0-9._-]+/g, "_")
    .slice(0, 120) || "worksheet";

export const staticWorksheetStorageKey = (
  email: string,
  worksheetId: string,
): string =>
  `app.staticWorksheetProgress.${String(email || "desktop-local-user").trim().toLowerCase()}.${safeWorksheetId(worksheetId)}`;

const runtimeStyle = `
<style id="upcurved-static-worksheet-runtime-style">
  .upcurved-worksheet-runtime-toolbar {
    position: sticky;
    top: 0;
    z-index: 9999;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    padding: 10px 12px;
    margin: 0 0 14px;
    border-bottom: 1px solid #d1d5db;
    background: rgba(255,255,255,.97);
    color: #111827;
    font: 14px/1.35 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  }
  .upcurved-worksheet-runtime-toolbar button {
    appearance: none;
    border: 1px solid #9ca3af;
    border-radius: 7px;
    background: #fff;
    color: #111827;
    padding: 7px 11px;
    font: inherit;
    font-weight: 600;
    cursor: pointer;
  }
  .upcurved-worksheet-runtime-toolbar button:hover { background: #f3f4f6; }
  .upcurved-worksheet-runtime-status { color: #4b5563; font-size: 12px; }
  @media print {
    .upcurved-worksheet-runtime-toolbar { display: none !important; }
    textarea { overflow: visible !important; }
  }
</style>`;

export type WorksheetLabels = {
  progressRestored: string;
  progressSaved: string;
  saving: string;
  progressUnavailable: string;
  print: string;
};

// Injected into the generated worksheet as JS/HTML source, so the strings are
// interpolated as literals rather than resolved through a hook at runtime.
const DEFAULT_WORKSHEET_LABELS: WorksheetLabels = {
  progressRestored: "Progress restored",
  progressSaved: "Progress saved",
  saving: "Saving…",
  progressUnavailable: "This browser could not save progress locally",
  print: "Print / Save as PDF",
};

const runtimeScript = (worksheetId: string, labels: WorksheetLabels): string => {
  const idLiteral = JSON.stringify(safeWorksheetId(worksheetId));
  return `<script id="upcurved-static-worksheet-runtime-script">
(() => {
  const worksheetId = ${idLiteral};
  const standaloneKey = "upcurved.staticWorksheet." + worksheetId;
  const status = document.getElementById("upcurved-worksheet-save-status");
  const saveButton = document.getElementById("upcurved-worksheet-save");
  const printButton = document.getElementById("upcurved-worksheet-print");
  let saveTimer = null;

  const responseControls = () => Array.from(document.querySelectorAll("input, textarea, select")).filter((el) => {
    const type = String(el.getAttribute("type") || "").toLowerCase();
    return !["button", "submit", "reset", "hidden"].includes(type);
  });

  const snapshot = () => responseControls().map((el, index) => ({
    index,
    tag: el.tagName.toLowerCase(),
    type: String(el.getAttribute("type") || "").toLowerCase(),
    name: el.getAttribute("name") || "",
    value: "value" in el ? String(el.value ?? "") : "",
    checked: "checked" in el ? Boolean(el.checked) : false,
  }));

  const applyResponses = (responses) => {
    if (!Array.isArray(responses)) return;
    const controls = responseControls();
    responses.forEach((saved) => {
      if (!saved || !Number.isInteger(saved.index)) return;
      const el = controls[saved.index];
      if (!el) return;
      const type = String(el.getAttribute("type") || "").toLowerCase();
      if (type === "checkbox" || type === "radio") {
        el.checked = Boolean(saved.checked);
      } else if ("value" in el && typeof saved.value === "string") {
        el.value = saved.value;
      }
    });
    resizeTextareas();
  };

  const setStatus = (message) => {
    if (!status) return;
    status.textContent = message;
  };

  const tryLoadLocal = () => {
    try {
      const raw = localStorage.getItem(standaloneKey);
      if (!raw) return false;
      applyResponses(JSON.parse(raw));
      setStatus(${JSON.stringify(labels.progressRestored)});
      return true;
    } catch {
      return false;
    }
  };

  const trySaveLocal = (responses) => {
    try {
      localStorage.setItem(standaloneKey, JSON.stringify(responses));
      return true;
    } catch {
      return false;
    }
  };

  const saveProgress = (announce = true) => {
    const responses = snapshot();
    if (trySaveLocal(responses)) {
      if (announce) setStatus(${JSON.stringify(labels.progressSaved)});
      return;
    }
    if (window.parent && window.parent !== window) {
      window.parent.postMessage({
        type: "upcurved-static-worksheet-save",
        worksheetId,
        responses,
        announce,
      }, "*");
      if (announce) setStatus(${JSON.stringify(labels.saving)});
      return;
    }
    if (announce) setStatus(${JSON.stringify(labels.progressUnavailable)});
  };

  const resizeTextareas = () => {
    document.querySelectorAll("textarea").forEach((textarea) => {
      textarea.style.height = "auto";
      textarea.style.height = Math.max(textarea.scrollHeight, 48) + "px";
    });
  };

  const scheduleSave = () => {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(() => saveProgress(false), 450);
  };

  window.addEventListener("message", (event) => {
    const data = event.data || {};
    if (data.worksheetId !== worksheetId) return;
    if (data.type === "upcurved-static-worksheet-restore") {
      applyResponses(data.responses);
      if (Array.isArray(data.responses) && data.responses.length) {
        setStatus(${JSON.stringify(labels.progressRestored)});
      }
    } else if (data.type === "upcurved-static-worksheet-saved") {
      if (data.announce !== false) setStatus(${JSON.stringify(labels.progressSaved)});
    }
  });

  document.addEventListener("submit", (event) => event.preventDefault(), true);
  document.addEventListener("input", () => { resizeTextareas(); scheduleSave(); }, true);
  document.addEventListener("change", scheduleSave, true);
  window.addEventListener("beforeprint", resizeTextareas);

  if (saveButton) saveButton.addEventListener("click", () => saveProgress(true));
  if (printButton) printButton.addEventListener("click", () => {
    saveProgress(false);
    resizeTextareas();
    window.print();
  });

  resizeTextareas();
  if (!tryLoadLocal() && window.parent && window.parent !== window) {
    window.parent.postMessage({
      type: "upcurved-static-worksheet-restore-request",
      worksheetId,
    }, "*");
  }
})();
</script>`;
};

const runtimeToolbar = (worksheetId: string, labels: WorksheetLabels): string => `
<div class="upcurved-worksheet-runtime-toolbar" data-upcurved-static-worksheet-id="${safeWorksheetId(worksheetId)}">
  <button id="upcurved-worksheet-save" type="button">Save Progress</button>
  <button id="upcurved-worksheet-print" type="button">${labels.print}</button>
  <span id="upcurved-worksheet-save-status" class="upcurved-worksheet-runtime-status" aria-live="polite"></span>
</div>`;

export const prepareStaticWorksheetHtml = (
  sourceHtml: string,
  worksheetId: string,
  labels: WorksheetLabels = DEFAULT_WORKSHEET_LABELS,
): string => {
  let html = String(sourceHtml || "");
  // Defensive cleanup in case a previously prepared copy is re-opened.
  html = html
    .replace(/<style id=["']upcurved-static-worksheet-runtime-style["'][\s\S]*?<\/style>/gi, "")
    .replace(/<script id=["']upcurved-static-worksheet-runtime-script["'][\s\S]*?<\/script>/gi, "")
    .replace(/<div class=["']upcurved-worksheet-runtime-toolbar["'][\s\S]*?<\/div>/gi, "");

  const style = runtimeStyle;
  const toolbar = runtimeToolbar(worksheetId, labels);
  const script = runtimeScript(worksheetId, labels);

  if (/<\/head>/i.test(html)) {
    html = html.replace(/<\/head>/i, `${style}\n</head>`);
  } else {
    html = `${style}\n${html}`;
  }

  if (/<body\b[^>]*>/i.test(html)) {
    html = html.replace(/<body\b([^>]*)>/i, `<body$1>\n${toolbar}`);
  } else {
    html = `${toolbar}\n${html}`;
  }

  if (/<\/body>/i.test(html)) {
    html = html.replace(/<\/body>/i, `${script}\n</body>`);
  } else {
    html += `\n${script}`;
  }
  return html;
};
