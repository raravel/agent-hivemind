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

  // Debug: log to temp file to confirm hook is firing
  try {
    fs.appendFileSync(
      path.join(require("os").tmpdir(), "hv-hook-debug.log"),
      `${new Date().toISOString()} event=${event} cwd=${cwd}\n`,
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
    // Log user input
    const userPrompt = input.user_prompt || "";
    if (userPrompt.trim()) {
      const timestamp = new Date().toISOString().slice(11, 19);
      const entry = `## User [${timestamp}]\n\n${userPrompt.trim()}\n\n`;
      fs.appendFileSync(logFile, entry, "utf-8");
    }
  } else if (event === "Stop") {
    // Read transcript to get last assistant message
    const transcriptPath = input.transcript_path;
    if (transcriptPath && fs.existsSync(transcriptPath)) {
      try {
        const lines = fs
          .readFileSync(transcriptPath, "utf-8")
          .trim()
          .split("\n");

        // Walk backwards to find last assistant message
        for (let i = lines.length - 1; i >= 0; i--) {
          let msg;
          try {
            msg = JSON.parse(lines[i]);
          } catch {
            continue;
          }

          if (msg.role === "assistant") {
            // Extract text content (skip tool_use blocks)
            let text = "";
            if (typeof msg.content === "string") {
              text = msg.content;
            } else if (Array.isArray(msg.content)) {
              text = msg.content
                .filter((b) => b.type === "text")
                .map((b) => b.text)
                .join("\n");
            }

            if (text.trim()) {
              const timestamp = new Date().toISOString().slice(11, 19);
              const entry = `## Assistant [${timestamp}]\n\n${text.trim()}\n\n`;
              fs.appendFileSync(logFile, entry, "utf-8");
            }
            break;
          }
        }
      } catch {
        // ignore transcript read errors
      }
    }
  }

  process.stdout.write(JSON.stringify({ status: "approve" }));
}

main();
