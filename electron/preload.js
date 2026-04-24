const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("lawgicEU", {
  // Pipeline verbs — three separate ingestion flows
  status:                  ()         => ipcRenderer.invoke("pipeline-status"),
  incrementalLaws:         (opts)     => ipcRenderer.invoke("pipeline-incremental-laws", opts),
  incrementalCases:        (opts)     => ipcRenderer.invoke("pipeline-incremental-cases", opts),
  incrementalAmendments:   (opts)     => ipcRenderer.invoke("pipeline-incremental-amendments", opts),
  addLanguage:             (opts)     => ipcRenderer.invoke("pipeline-add-language", opts),
  estimateCost:            (opts)     => ipcRenderer.invoke("pipeline-estimate-cost", opts),
  verifyCache:             ()         => ipcRenderer.invoke("pipeline-verify-cache"),
  evalExtraction:          (opts)     => ipcRenderer.invoke("pipeline-eval-extraction", opts),
  stop:                    ()         => ipcRenderer.invoke("stop-pipeline"),

  // Settings
  loadSettings:            ()         => ipcRenderer.invoke("load-settings"),
  saveSettings:            (settings) => ipcRenderer.invoke("save-settings", settings),

  // Logs
  getLogInfo:              ()         => ipcRenderer.invoke("get-log-info"),

  // Event streams
  onEvent:                 (cb)       => ipcRenderer.on("pipeline-event", (_, d) => cb(d)),
  onLog:                   (cb)       => ipcRenderer.on("pipeline-log",   (_, d) => cb(d)),
  onDone:                  (cb)       => ipcRenderer.on("pipeline-done",  (_, d) => cb(d)),
  onError:                 (cb)       => ipcRenderer.on("pipeline-error", (_, d) => cb(d)),
});
