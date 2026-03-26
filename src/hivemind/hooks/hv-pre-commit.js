// Claude Code PreToolUse hook
// Intercepts Bash tool calls containing "git commit"
// Injects spec sync reminders when .hivemind-link.json exists
//
// Input (stdin):  JSON with { tool_name, tool_input }
// Output (stdout): JSON with { status, additionalContext? }

const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

function main() {
  // Read JSON from stdin
  let input;
  try {
    const raw = fs.readFileSync(0, "utf-8");
    input = JSON.parse(raw);
  } catch {
    // If stdin is empty or invalid JSON, approve by default
    process.stdout.write(JSON.stringify({ status: "approve" }));
    return;
  }

  const toolName = input.tool_name;
  const toolInput = input.tool_input || {};

  // 1. If not a Bash tool call, approve immediately
  if (toolName !== "Bash") {
    process.stdout.write(JSON.stringify({ status: "approve" }));
    return;
  }

  // 2. If the command doesn't contain "git commit", approve
  const command = toolInput.command || "";
  if (!command.includes("git commit")) {
    process.stdout.write(JSON.stringify({ status: "approve" }));
    return;
  }

  // 3. Check if .hivemind-link.json exists in cwd
  const linkPath = path.join(process.cwd(), ".hivemind-link.json");
  if (!fs.existsSync(linkPath)) {
    process.stdout.write(JSON.stringify({ status: "approve" }));
    return;
  }

  // 4. Read .hivemind-link.json to get the project name
  let linkData;
  try {
    linkData = JSON.parse(fs.readFileSync(linkPath, "utf-8"));
  } catch {
    // If file is malformed, approve without reminder
    process.stdout.write(JSON.stringify({ status: "approve" }));
    return;
  }

  const projectName = linkData.project || "unknown";

  // 5. Get staged files via git diff --cached --name-only
  let stagedFiles;
  try {
    const output = execSync("git diff --cached --name-only", {
      encoding: "utf-8",
      timeout: 5000,
    });
    stagedFiles = output.trim();
  } catch {
    // If git command fails, approve without reminder
    process.stdout.write(JSON.stringify({ status: "approve" }));
    return;
  }

  if (!stagedFiles) {
    process.stdout.write(JSON.stringify({ status: "approve" }));
    return;
  }

  // 6. Build reminder message
  const reminder =
    "Remember to update harness specs in projects/" +
    projectName +
    "/ if these code changes affect documented architecture or features: " +
    stagedFiles.split("\n").join(", ");

  process.stdout.write(
    JSON.stringify({ status: "approve", additionalContext: reminder })
  );
}

main();
