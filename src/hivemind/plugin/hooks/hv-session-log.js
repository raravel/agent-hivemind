/**
 * hv-session-log.js — Real-time L3 session logger
 *
 * Hooks:
 *   UserPromptSubmit — logs user input immediately
 *   Stop             — reads transcript, logs last assistant output
 *
 * Writes to: ~/agent-hivemind-data/level3/{project}/{date}_{session}.md
 */

const fs = require("fs");
const path = require("path");

function main() {
  let raw = "";
  try {
    raw = fs.readFileSync(0, "utf-8");
  } catch {
    process.stdout.write(JSON.stringify({ status: "approve" }));
    return;
  }

  let input;
  try {
    input = JSON.parse(raw);
  } catch {
    process.stdout.write(JSON.stringify({ status: "approve" }));
    return;
  }

  const cwd = input.cwd || process.cwd();
  const sessionId = input.session_id || "unknown";
  const event = input.hook_event_name;

  // Debug: dump full input keys and values to diagnose
  try {
    const debugPath = path.join(require("os").tmpdir(), "hv-hook-debug.log");
    const keys = Object.keys(input);
    const debugInfo = keys.map(k => {
      const v = input[k];
      const preview = typeof v === "string" ? v.slice(0, 200) : JSON.stringify(v).slice(0, 200);
      return `  ${k}: ${preview}`;
    }).join("\n");
    fs.appendFileSync(
      debugPath,
      `${new Date().toISOString()} event=${event}\n${debugInfo}\n\n`,
      "utf-8"
    );
  } catch { /* ignore */ }

  // Find .hivemind-link.json to get project name + data path
  const linkFile = path.join(cwd, ".hivemind-link.json");
  if (!fs.existsSync(linkFile)) {
    process.stdout.write(JSON.stringify({ status: "approve" }));
    return;
  }

  let linkData;
  try {
    linkData = JSON.parse(fs.readFileSync(linkFile, "utf-8"));
  } catch {
    process.stdout.write(JSON.stringify({ status: "approve" }));
    return;
  }

  const project = linkData.project;
  const dataPath = linkData.data_path;
  if (!project || !dataPath) {
    process.stdout.write(JSON.stringify({ status: "approve" }));
    return;
  }

  // Resolve log file path
  const resolvedDataPath = dataPath;
  const today = new Date().toISOString().slice(0, 10).replace(/-/g, "");
  const shortSession = sessionId.slice(0, 8);
  const logDir = path.join(resolvedDataPath, "level3", project);
  const logFile = path.join(logDir, `${today}_${shortSession}.md`);

  // Create directory if needed
  try {
    fs.mkdirSync(logDir, { recursive: true });
  } catch {
    // ignore
  }

  // Write header if file is new
  if (!fs.existsSync(logFile)) {
    const header =
      `---\nsession_id: "${sessionId}"\nproject: "${project}"\ndate: "${new Date().toISOString()}"\n---\n\n` +
      `# Session Log\n\n`;
    fs.writeFileSync(logFile, header, "utf-8");
  }

  if (event === "UserPromptSubmit") {
    const userPrompt = input.prompt || "";
    if (userPrompt.trim()) {
      const timestamp = new Date().toISOString().slice(11, 19);
      const entry = `## User [${timestamp}]\n\n${userPrompt.trim()}\n\n`;
      fs.appendFileSync(logFile, entry, "utf-8");
    }
  } else if (event === "Stop") {
    const assistantMsg = input.last_assistant_message || "";
    if (assistantMsg.trim()) {
      const timestamp = new Date().toISOString().slice(11, 19);
      const entry = `## Assistant [${timestamp}]\n\n${assistantMsg.trim()}\n\n`;
      fs.appendFileSync(logFile, entry, "utf-8");
    }
  }

  process.stdout.write(JSON.stringify({ status: "approve" }));
}

main();
