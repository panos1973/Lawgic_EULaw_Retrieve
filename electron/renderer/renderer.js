// Renderer-side glue. Talks to the main process via window.lawgicEU (see preload.js).

const $ = (id) => document.getElementById(id);
const byAttr = (attr, val) => document.querySelector(`[${attr}="${val}"]`);

const els = {
  language: $("sel-language"),
  scope: $("sel-scope"),
  refreshStatus: $("btn-refresh-status"),
  estimate: $("btn-estimate"),
  verify: $("btn-verify-cache"),
  evalBtn: $("btn-eval"),
  addLang: $("btn-add-lang"),
  settingsBtn: $("btn-settings"),
  activity: $("activity"),
  modal: $("settings-modal"),
  modalForm: $("settings-form"),
  modalClose: $("btn-close-settings"),
  modalCancel: $("btn-cancel-settings"),
  miniLaw: $("status-mini-law"),
  miniCase: $("status-mini-case"),
  miniAmend: $("status-mini-amendment"),
};

function appendActivity(level, text) {
  const cls = level === "error" ? "evt-err" : level === "warn" ? "evt-warn" : "evt-ok";
  const ts = new Date().toLocaleTimeString();
  const div = document.createElement("div");
  div.className = cls;
  div.textContent = `${ts}  ${text}`;
  els.activity.prepend(div);
  while (els.activity.children.length > 500) els.activity.removeChild(els.activity.lastChild);
}

function renderMini(container, counts) {
  const fields = [
    ["embedded", "ok"], ["enriched", "info"],
    ["fetched", "info"], ["discovered", "info"],
    ["failed_fetch", "err"], ["failed_enrich", "err"], ["failed_embed", "err"],
    ["missing_source", "warn"], ["superseded", "muted"],
  ];
  container.innerHTML = "";
  for (const [key, tone] of fields) {
    const n = counts?.[key] ?? 0;
    if (!n && tone === "err") continue;
    const chip = document.createElement("span");
    chip.className = `chip chip-${tone}`;
    chip.innerHTML = `<b>${n}</b> ${key.replace(/_/g, " ")}`;
    container.appendChild(chip);
  }
  if (!container.children.length) {
    container.innerHTML = `<span class="muted">No documents yet.</span>`;
  }
}

// Track which panel is "running" so only its stop button is live.
const panels = {
  "law":       { runBtn: byAttr("data-action", "run-laws"),       stopBtn: byAttr("data-action", "stop-laws"),       kind: "law" },
  "case":      { runBtn: byAttr("data-action", "run-cases"),      stopBtn: byAttr("data-action", "stop-cases"),      kind: "case" },
  "amendment": { runBtn: byAttr("data-action", "run-amendments"), stopBtn: byAttr("data-action", "stop-amendments"), kind: "amendment" },
};

function setPanelRunning(kind, running) {
  for (const [k, p] of Object.entries(panels)) {
    const isMe = k === kind;
    p.runBtn.disabled = running;
    p.stopBtn.disabled = !(running && isMe);
  }
  els.refreshStatus.disabled = running;
  els.estimate.disabled = running;
  els.verify.disabled = running;
  els.evalBtn.disabled = running;
}

// Event streams
window.lawgicEU.onEvent((event) => {
  if (!event || !event.type) return;
  switch (event.type) {
    case "log":
      appendActivity(event.level || "info", event.message || "");
      break;
    case "fetch_ok":
    case "add_language_doc_ok":
      appendActivity("ok", `OK ${event.celex || ""} ${event.language || ""}`);
      break;
    case "fetch_failed":
    case "add_language_doc_failed":
      appendActivity("error", `FAIL ${event.celex || ""} ${event.error || ""}`);
      break;
    case "fetch_missing_source":
      appendActivity("warn", `missing ${event.celex} in ${event.language || "?"}`);
      break;
    case "status_aggregate": {
      const counts = event.counts || {};
      renderMini(els.miniLaw, counts.law || counts);
      renderMini(els.miniCase, counts.case || {});
      renderMini(els.miniAmend, counts.amendment || {});
      break;
    }
    case "incremental_amendments_summary":
      appendActivity("ok", `Amendments pass 1: ${event.pass1_count} rows inserted`);
      break;
    case "pass1_completed":
      appendActivity("ok", `Pass 1 (CELLAR edges): ${event.count} rows`);
      break;
    case "cost_estimate":
      if (typeof event.total_usd === "number") {
        appendActivity("ok", `Estimated: $${event.total_usd.toFixed(2)} for ${event.scope}/${event.language}`);
      } else {
        appendActivity("info", JSON.stringify(event));
      }
      break;
    default:
      appendActivity("info", JSON.stringify(event));
  }
});

window.lawgicEU.onLog((text) => appendActivity("info", text.trim()));
window.lawgicEU.onDone(({ exitCode, verb }) => {
  appendActivity(exitCode === 0 ? "ok" : "error",
                 `> ${verb || "pipeline"} done (exit ${exitCode})`);
  setPanelRunning(null, false);
});
window.lawgicEU.onError((msg) => {
  appendActivity("error", msg);
  setPanelRunning(null, false);
});

// Panel actions
panels.law.runBtn.addEventListener("click", () => {
  setPanelRunning("law", true);
  window.lawgicEU.incrementalLaws({
    languages: [els.language.value], scope: els.scope.value,
  });
});
panels.case.runBtn.addEventListener("click", () => {
  setPanelRunning("case", true);
  window.lawgicEU.incrementalCases({
    languages: [els.language.value], scope: els.scope.value,
  });
});
panels.amendment.runBtn.addEventListener("click", () => {
  setPanelRunning("amendment", true);
  window.lawgicEU.incrementalAmendments({ limit: 2000 });
});
for (const p of Object.values(panels)) {
  p.stopBtn.addEventListener("click", () => window.lawgicEU.stop());
}

// Header / global
els.refreshStatus.addEventListener("click", () => {
  setPanelRunning("law", true);
  window.lawgicEU.status();
});
els.estimate.addEventListener("click", () => {
  setPanelRunning("law", true);
  window.lawgicEU.estimateCost({
    scope: els.scope.value === "all" ? "tier_b" : "tier_a",
    language: els.language.value,
    firstLanguage: els.language.value === "en",
  });
});
els.verify.addEventListener("click", () => {
  setPanelRunning("law", true);
  window.lawgicEU.verifyCache();
});
els.evalBtn.addEventListener("click", () => {
  setPanelRunning("law", true);
  window.lawgicEU.evalExtraction({ docs: 20 });
});
els.addLang.addEventListener("click", () => {
  const lang = prompt("Language code to add (e.g. el, de, fr, it)");
  if (!lang) return;
  setPanelRunning("law", true);
  window.lawgicEU.addLanguage({ language: lang });
});

// Settings modal
function openSettings() {
  els.modal.classList.remove("hidden");
  window.lawgicEU.loadSettings().then((s) => {
    if (!s) return;
    for (const el of els.modalForm.elements) {
      if (el.name && s[el.name] != null) el.value = s[el.name];
    }
  });
}
function closeSettings() { els.modal.classList.add("hidden"); }

els.settingsBtn.addEventListener("click", openSettings);
els.modalClose.addEventListener("click", closeSettings);
els.modalCancel.addEventListener("click", closeSettings);

els.modalForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = {};
  for (const el of els.modalForm.elements) {
    if (el.name) data[el.name] = el.value;
  }
  const r = await window.lawgicEU.saveSettings(data);
  if (r && r.error) appendActivity("error", "Save failed: " + r.error);
  else appendActivity("ok", "Settings saved.");
  closeSettings();
});
