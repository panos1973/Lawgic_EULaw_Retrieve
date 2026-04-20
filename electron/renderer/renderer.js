// Renderer-side glue. Talks to the main process via window.lawgicEU (see preload.js).

const $ = (id) => document.getElementById(id);

const els = {
  language: $("sel-language"),
  scope: $("sel-scope"),
  status: $("btn-status"),
  incremental: $("btn-incremental"),
  addLang: $("btn-add-lang"),
  estimate: $("btn-estimate"),
  stop: $("btn-stop"),
  verify: $("btn-verify-cache"),
  evalBtn: $("btn-eval"),
  settingsBtn: $("btn-settings"),
  statusGrid: $("status-grid"),
  activity: $("activity"),
  modal: $("settings-modal"),
  modalForm: $("settings-form"),
  modalClose: $("btn-close-settings"),
  modalCancel: $("btn-cancel-settings"),
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

function renderStatusCounts(counts) {
  const order = ["embedded", "enriched", "fetched", "discovered",
                 "failed_fetch", "failed_enrich", "failed_embed",
                 "failed_integrity", "missing_source", "superseded"];
  els.statusGrid.innerHTML = "";
  for (const key of order) {
    const val = counts[key] ?? 0;
    const card = document.createElement("div");
    card.className = "status-card";
    card.innerHTML = `<div class="label">${key.replace(/_/g, " ")}</div><div class="value">${val}</div>`;
    els.statusGrid.appendChild(card);
  }
}

function setRunning(on) {
  els.status.disabled = on;
  els.incremental.disabled = on;
  els.estimate.disabled = on;
  els.verify.disabled = on;
  els.evalBtn.disabled = on;
  els.stop.disabled = !on;
}

// Event stream handlers
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
    case "status_aggregate":
      renderStatusCounts(event.counts || {});
      break;
    case "cost_estimate":
      appendActivity("ok", `Estimated: $${event.total_usd.toFixed(2)} for ${event.scope}/${event.language}`);
      break;
    default:
      appendActivity("info", JSON.stringify(event));
  }
});

window.lawgicEU.onLog((text) => appendActivity("info", text.trim()));
window.lawgicEU.onDone(({ exitCode, verb }) => {
  appendActivity(exitCode === 0 ? "ok" : "error",
                 `> ${verb || "pipeline"} done (exit ${exitCode})`);
  setRunning(false);
});
window.lawgicEU.onError((msg) => {
  appendActivity("error", msg);
  setRunning(false);
});

// Button wiring
els.status.addEventListener("click", () => {
  setRunning(true);
  window.lawgicEU.status();
});

els.incremental.addEventListener("click", () => {
  setRunning(true);
  window.lawgicEU.incremental({
    languages: [els.language.value],
    scope: els.scope.value,
  });
});

els.addLang.addEventListener("click", () => {
  const lang = prompt("Language code to add (e.g. el, de, fr, it)");
  if (!lang) return;
  setRunning(true);
  window.lawgicEU.addLanguage({ language: lang });
});

els.estimate.addEventListener("click", () => {
  setRunning(true);
  window.lawgicEU.estimateCost({
    scope: els.scope.value === "all" ? "tier_b" : "tier_a",
    language: els.language.value,
    firstLanguage: els.language.value === "en",
  });
});

els.stop.addEventListener("click", () => window.lawgicEU.stop());
els.verify.addEventListener("click", () => {
  setRunning(true);
  window.lawgicEU.verifyCache();
});
els.evalBtn.addEventListener("click", () => {
  setRunning(true);
  window.lawgicEU.evalExtraction({ docs: 20 });
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
