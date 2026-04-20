// Electron main process for Lawgic_EULaw_Retrieve.
//
// IPC verbs implement the flows in docs/handoff/08_ELECTRON_APP.md:
//   status          — query EULawIngestionStatus aggregates
//   incremental     — run Atom-feed-based incremental update
//   add-language    — layer a new language's text + vectors onto existing docs
//   estimate-cost   — dry-run cost projection
//   verify-cache    — one-off DashScope caching probe
//   eval-extraction — 20-doc quality eval across models
//
// Settings (API keys, endpoints, model overrides) are persisted to the
// user's app data dir (userData). They are injected as env vars into the
// spawned Python subprocess — never hardcoded, never committed.

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
    const ts = new Date().toISOString();
    currentLogStream.write(`[${ts}] ${line}\n`);
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
    width: 1280, height: 860, minWidth: 980, minHeight: 640,
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

// ── Settings: persist to userData dir (survives reinstall) ──────────────
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

// Merge settings into the Python subprocess environment.
function envFromSettings(settings) {
  const env = { ...process.env, LAWGIC_EULAW_DATA_DIR: DATA_DIR };
  if (settings.dashscope_api_key) env.DASHSCOPE_API_KEY = settings.dashscope_api_key;
  if (settings.dashscope_base_url) env.DASHSCOPE_BASE_URL = settings.dashscope_base_url;
  if (settings.voyage_api_key) env.VOYAGE_API_KEY = settings.voyage_api_key;
  if (settings.google_ai_studio_key) env.GOOGLE_AI_STUDIO_API_KEY = settings.google_ai_studio_key;
  if (settings.weaviate_host) env.WEAVIATE_HOST = settings.weaviate_host;
  if (settings.weaviate_api_key) env.WEAVIATE_API_KEY = settings.weaviate_api_key;
  if (settings.database_url) env.DATABASE_URL = settings.database_url;
  if (settings.llm_concurrency) env.LLM_CONCURRENCY = String(settings.llm_concurrency);
  return env;
}

// Run a Python script + args. Streams stdout lines (JSON events) to the
// renderer via 'pipeline-event'; stderr + non-JSON stdout goes to
// 'pipeline-log'. Only one pipeline may run at a time.
function runPython({ script, args, verb }) {
  if (pythonProcess) return Promise.resolve({ error: "Pipeline already running" });
  openLogStream(verb);
  const settings = loadSettingsSync();
  const env = envFromSettings(settings);
  const pyCmd = process.platform === "win32" ? "python" : "python3";
  const fullArgs = [script, ...args];

  return new Promise((resolve) => {
    pythonProcess = spawn(pyCmd, fullArgs, { cwd: PROJECT_ROOT, env });
    pythonProcess.stdout.on("data", (data) => {
      for (const line of data.toString().split("\n").filter(Boolean)) {
        writeLog(line);
        try { mainWindow.webContents.send("pipeline-event", JSON.parse(line)); }
        catch { mainWindow.webContents.send("pipeline-log", line); }
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

// ── IPC verbs ───────────────────────────────────────────────────────────

ipcMain.handle("pipeline-status", async () => {
  return runPython({
    script: path.join(PYTHON_DIR, "pipeline.py"),
    args: ["status", "--json"],
    verb: "status",
  });
});

ipcMain.handle("pipeline-incremental", async (_event, opts = {}) => {
  const languages = (opts.languages || ["en"]).join(",");
  const scope = opts.scope || "priority";
  return runPython({
    script: path.join(PYTHON_DIR, "pipeline.py"),
    args: ["incremental", "--languages", languages, "--scope", scope],
    verb: "incremental",
  });
});

ipcMain.handle("pipeline-add-language", async (_event, { language }) => {
  return runPython({
    script: path.join(PYTHON_DIR, "pipeline.py"),
    args: ["add-language", "--language", language],
    verb: "add-language",
  });
});

ipcMain.handle("pipeline-estimate-cost", async (_event, { scope = "tier_a", language = "en", firstLanguage = false }) => {
  return runPython({
    script: path.join(SCRIPTS_DIR, "estimate_cost.py"),
    args: ["--scope", scope, "--language", language, ...(firstLanguage ? ["--first-language"] : [])],
    verb: "estimate-cost",
  });
});

ipcMain.handle("pipeline-verify-cache", async () => {
  return runPython({
    script: path.join(SCRIPTS_DIR, "verify_qwen_cache.py"),
    args: [],
    verb: "verify-cache",
  });
});

ipcMain.handle("pipeline-eval-extraction", async (_event, { docs = 20, models = "qwen3.5-flash,qwen3.6-plus,gemini-2.5-flash" }) => {
  return runPython({
    script: path.join(SCRIPTS_DIR, "eval_extraction.py"),
    args: ["--docs", String(docs), "--models", models],
    verb: "eval-extraction",
  });
});

ipcMain.handle("stop-pipeline", () => {
  if (!pythonProcess) return { stopped: false };
  try {
    const marker = path.join(DATA_DIR, ".clean_stop_requested");
    fs.writeFileSync(marker, new Date().toISOString(), "utf-8");
  } catch {}
  pythonProcess.kill("SIGTERM");
  pythonProcess = null;
  return { stopped: true };
});

ipcMain.handle("get-log-info", () => ({
  logsDir: LOGS_DIR,
  currentLogFile: currentLogFile,
}));
