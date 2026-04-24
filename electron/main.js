// Electron main process for Lawgic_EULaw_Retrieve.
//
// IPC verbs (per docs/handoff/08_ELECTRON_APP.md):
//   status                    - counts from EULawIngestionStatus
//   incremental-laws          - new EU legislation
//   incremental-cases         - new EU court decisions
//   incremental-amendments    - new EUAmendments rows (needs laws already ingested)
//   add-language              - layer a new language onto existing chunks
//   estimate-cost             - dry-run cost projection
//   verify-cache              - DashScope caching probe
//   eval-extraction           - 20-doc quality eval
//
// Settings persist to userData (survives reinstall). Injected as env vars
// into the spawned Python subprocess - never hardcoded.

const { app, BrowserWindow, ipcMain } = require("electron");
const path = require("path");
const { spawn } = require("child_process");
const fs = require("fs");

const IS_PACKAGED = app.isPackaged;
const PROJECT_ROOT = IS_PACKAGED ? process.resourcesPath : path.join(__dirname, "..");
const PYTHON_DIR = path.join(PROJECT_ROOT, "python");
const SCRIPTS_DIR = path.join(PROJECT_ROOT, "scripts");

const DATA_DIR = IS_PACKAGED
  ? path.join(app.getPath("home"), "LawgicEULawData")
  : path.join(PROJECT_ROOT, "data");
try { fs.mkdirSync(DATA_DIR, { recursive: true }); } catch {}

const SETTINGS_DIR = path.join(app.getPath("userData"), "settings");
const SETTINGS_FILE = path.join(SETTINGS_DIR, "app_settings.json");

const LOGS_DIR = path.join(DATA_DIR, "logs");
try { fs.mkdirSync(LOGS_DIR, { recursive: true }); } catch {}

let mainWindow;
let pythonProcess = null;
let currentLogStream = null;
let currentLogFile = null;

function openLogStream(verb) {
  try {
    if (currentLogStream) { try { currentLogStream.end(); } catch {} currentLogStream = null; }
    const ts = new Date().toISOString().replace(/[:.]/g, "-");
    currentLogFile = path.join(LOGS_DIR, `pipeline_${verb}_${ts}.log`);
    currentLogStream = fs.createWriteStream(currentLogFile, { flags: "a" });
    currentLogStream.write(`# Pipeline log started at ${new Date().toISOString()}\n# Verb: ${verb}\n\n`);
  } catch (e) { console.error("log open failed", e); }
}

function writeLog(line) {
  if (!currentLogStream) return;
  try {
    currentLogStream.write(`[${new Date().toISOString()}] ${line}\n`);
  } catch {}
}

function closeLogStream() {
  if (currentLogStream) {
    try {
      currentLogStream.write(`\n# Pipeline log closed at ${new Date().toISOString()}\n`);
      currentLogStream.end();
    } catch {}
    currentLogStream = null;
  }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1320, height: 900, minWidth: 1080, minHeight: 700,
    titleBarStyle: "hiddenInset", backgroundColor: "#f5f6f8",
    icon: path.join(PROJECT_ROOT, "assets", "icon.png"),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  mainWindow.loadFile(path.join(__dirname, "renderer", "index.html"));
}

app.whenReady().then(createWindow);
app.on("window-all-closed", () => {
  if (pythonProcess) pythonProcess.kill();
  if (process.platform !== "darwin") app.quit();
});
app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});

// Settings
function loadSettingsSync() {
  try { return JSON.parse(fs.readFileSync(SETTINGS_FILE, "utf-8")); }
  catch { return {}; }
}

ipcMain.handle("load-settings", async () => loadSettingsSync());

ipcMain.handle("save-settings", async (_event, settings) => {
  try {
    fs.mkdirSync(SETTINGS_DIR, { recursive: true });
    fs.writeFileSync(SETTINGS_FILE, JSON.stringify(settings, null, 2), "utf-8");
    return { ok: true };
  } catch (e) { return { error: e.message }; }
});

// Weaviate-only stack: no DATABASE_URL anymore.
function envFromSettings(settings) {
  const env = { ...process.env, LAWGIC_EULAW_DATA_DIR: DATA_DIR };
  if (settings.dashscope_api_key) env.DASHSCOPE_API_KEY = settings.dashscope_api_key;
  if (settings.dashscope_base_url) env.DASHSCOPE_BASE_URL = settings.dashscope_base_url;
  if (settings.voyage_api_key) env.VOYAGE_API_KEY = settings.voyage_api_key;
  if (settings.google_ai_studio_key) env.GOOGLE_AI_STUDIO_API_KEY = settings.google_ai_studio_key;
  if (settings.weaviate_host) env.WEAVIATE_HOST = settings.weaviate_host;
  if (settings.weaviate_api_key) env.WEAVIATE_API_KEY = settings.weaviate_api_key;
  if (settings.llm_concurrency) env.LLM_CONCURRENCY = String(settings.llm_concurrency);
  return env;
}

function runPython({ script, args, verb }) {
  if (pythonProcess) return Promise.resolve({ error: "Pipeline already running" });
  openLogStream(verb);
  const env = envFromSettings(loadSettingsSync());
  const pyCmd = process.platform === "win32" ? "python" : "python3";

  return new Promise((resolve) => {
    pythonProcess = spawn(pyCmd, [script, ...args], { cwd: PROJECT_ROOT, env });
    pythonProcess.stdout.on("data", (data) => {
      for (const line of data.toString().split("\n").filter(Boolean)) {
        writeLog(line);
        try {
          const evt = JSON.parse(line);
          evt._verb = verb;
          mainWindow.webContents.send("pipeline-event", evt);
        } catch { mainWindow.webContents.send("pipeline-log", line); }
      }
    });
    pythonProcess.stderr.on("data", (data) => {
      const text = data.toString();
      writeLog("[STDERR] " + text);
      mainWindow.webContents.send("pipeline-log", text);
    });
    pythonProcess.on("close", (code) => {
      writeLog(`\n# Process closed with exit code ${code}`);
      closeLogStream();
      pythonProcess = null;
      mainWindow.webContents.send("pipeline-done", { exitCode: code, verb });
      resolve({ exitCode: code });
    });
    pythonProcess.on("error", (err) => {
      writeLog(`\n# Process error: ${err.message}`);
      closeLogStream();
      pythonProcess = null;
      mainWindow.webContents.send("pipeline-error", err.message);
      resolve({ error: err.message });
    });
  });
}

// Pipeline verbs

ipcMain.handle("pipeline-status", async () => {
  return runPython({
    script: path.join(PYTHON_DIR, "pipeline.py"),
    args: ["status", "--json"],
    verb: "status",
  });
});

ipcMain.handle("pipeline-incremental-laws", async (_e, opts = {}) => {
  return runPython({
    script: path.join(PYTHON_DIR, "pipeline.py"),
    args: ["incremental-laws",
           "--languages", (opts.languages || ["en"]).join(","),
           "--scope", opts.scope || "priority"],
    verb: "incremental-laws",
  });
});

ipcMain.handle("pipeline-incremental-cases", async (_e, opts = {}) => {
  return runPython({
    script: path.join(PYTHON_DIR, "pipeline.py"),
    args: ["incremental-cases",
           "--languages", (opts.languages || ["en"]).join(","),
           "--scope", opts.scope || "priority"],
    verb: "incremental-cases",
  });
});

ipcMain.handle("pipeline-incremental-amendments", async (_e, opts = {}) => {
  return runPython({
    script: path.join(PYTHON_DIR, "pipeline.py"),
    args: ["incremental-amendments", "--limit", String(opts.limit || 2000)],
    verb: "incremental-amendments",
  });
});

ipcMain.handle("pipeline-add-language", async (_e, { language }) => {
  return runPython({
    script: path.join(PYTHON_DIR, "pipeline.py"),
    args: ["add-language", "--language", language],
    verb: "add-language",
  });
});

ipcMain.handle("pipeline-estimate-cost", async (_e, opts = {}) => {
  const args = ["--scope", opts.scope || "tier_a",
                "--language", opts.language || "en"];
  if (opts.firstLanguage) args.push("--first-language");
  return runPython({
    script: path.join(SCRIPTS_DIR, "estimate_cost.py"),
    args, verb: "estimate-cost",
  });
});

ipcMain.handle("pipeline-verify-cache", async () => {
  return runPython({
    script: path.join(SCRIPTS_DIR, "verify_qwen_cache.py"),
    args: [], verb: "verify-cache",
  });
});

ipcMain.handle("pipeline-eval-extraction", async (_e, opts = {}) => {
  return runPython({
    script: path.join(SCRIPTS_DIR, "eval_extraction.py"),
    args: ["--docs", String(opts.docs || 20),
           "--models", opts.models || "qwen3.5-flash,qwen3.6-plus,gemini-2.5-flash"],
    verb: "eval-extraction",
  });
});

ipcMain.handle("stop-pipeline", () => {
  if (!pythonProcess) return { stopped: false };
  try {
    fs.writeFileSync(path.join(DATA_DIR, ".clean_stop_requested"),
                     new Date().toISOString(), "utf-8");
  } catch {}
  pythonProcess.kill("SIGTERM");
  pythonProcess = null;
  return { stopped: true };
});

ipcMain.handle("get-log-info", () => ({
  logsDir: LOGS_DIR,
  currentLogFile: currentLogFile,
}));
