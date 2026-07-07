// ⚠️ BLOCKED — DO NOT USE AS-IS (confirmed 2026-06-18 UAT M3).
// Phase 2 below calls agent("/skill-iterate ..."), but a Workflow agent() is DEPTH-1 and has
// NO Agent/Task tool (empirically verified). /skill-iterate requires its own render + grade
// sub-agents per iteration, which a depth-1 agent cannot spawn — it would degrade to
// single-context inline iteration, the EXACT failure mode m2_launcher was built to avoid
// (2026-05-27: single sessions burn context across N skills). Worse, m2_launcher needs BOTH
// fresh-context-per-skill AND nested fan-out; only a `claude -p` subprocess (a full session)
// gives both — a depth-1 Workflow agent gives fresh context but cannot fan out. So the
// claude->Workflow migration premise CANNOT hold for m2_launcher without losing one property.
// Recommendation (needs operator decision): keep m2_launcher on the `claude -p` subprocess
// path (m2_launcher.py spawn loop), which this Workflow was meant to replace.
//
// m2_launcher.workflow.js — Workflow bridge for M2 per-skill /skill-iterate launcher.
//
// Replaces the `claude -p` subprocess spawns in m2_launcher.py with session agent() calls,
// keeping queue resolution and manifest writing in the Python CLI. Three phases:
//
//   Phase 1: m2_launcher.py --export-queue   → get skill list as JSON
//   Phase 2: serial agent() per skill        → /skill-iterate for each skill (fresh context per call)
//   Phase 3: m2_launcher.py --write-manifest → write _summary.md from results JSON
//
// Invocation (from a Claude Code session):
//   Workflow({
//     scriptPath: ".claude/skills/skill-iterate/scripts/m2_launcher.workflow.js",
//     args: { iters: 5, budget: "2h", skip_list: "", workspace: "<workspace>" }
//   })
//
// Serial (NOT parallel) — each /skill-iterate call needs a fresh context window.
// Using parallel() here would multiplex N skills into one shared context window,
// which is exactly the failure mode m2_launcher.py was designed to avoid.
//
// The Python script (m2_launcher.py) is still used for:
//   - Queue resolution (--export-queue)
//   - Manifest writing (--write-manifest)
// This Workflow only replaces the subprocess spawn loop.

export const meta = {
  name: "m2-launcher",
  description: "Run M2 per-skill /skill-iterate fleet via Workflow: export queue, serial agent() per skill, write manifest",
  phases: [
    { title: "Export queue", detail: "m2_launcher.py --export-queue → skill list JSON" },
    { title: "Run skills", detail: "serial agent(/skill-iterate --skill X ...) per skill" },
    { title: "Write manifest", detail: "m2_launcher.py --write-manifest → _summary.md" },
  ],
}

// args shape:
// {
//   iters?: number        // --per-skill-iterations per skill (default 5)
//   budget?: string       // --per-skill-budget per skill (default "2h")
//   skip_list?: string    // comma-separated extra skip list (default "")
//   workspace?: string    // workspace root (default "<workspace>")
//   queue_file?: string   // path to a queue file (one skill per line); omit to auto-discover
// }

// Normalize args: the Workflow tool boundary may deliver args as a JSON STRING rather
// than an object. Accept either so the documented Workflow({args: {...}}) call works.
const A = (typeof args === "string")
  ? (() => { try { return JSON.parse(args) } catch (e) { return {} } })()
  : (args || {})

const iters = (A && A.iters != null) ? A.iters : 5
const budget = (A && A.budget) ? A.budget : "2h"
const skipList = (A && A.skip_list) ? A.skip_list : ""
const workspace = (A && A.workspace) ? A.workspace : "<workspace>"
const queueFile = (A && A.queue_file) ? A.queue_file : null

const launcherPath = "~\\dev\\.claude\\skills\\skill-iterate\\scripts\\m2_launcher.py"
const logsBase = "~\\dev\\docs\\skill-iterate-runs"

// ── Phase 1: Export queue ─────────────────────────────────────────────────────
phase("Export queue")
log(`Resolving skill queue via m2_launcher.py --export-queue ...`)

const queueFlagStr = queueFile ? ` --queue "${queueFile}"` : ""
const skipFlagStr = skipList ? ` --skip-list "${skipList}"` : ""

const queueOutput = await agent(
  `Run the following PowerShell command and return ONLY the raw JSON it prints to stdout (nothing else — no explanation, no markdown fences, just the raw JSON):

\`\`\`powershell
python "${launcherPath}"${queueFlagStr}${skipFlagStr} --workspace "${workspace}" --export-queue
\`\`\`

Return the JSON verbatim.`,
  { label: "export-queue", phase: "Export queue" },
)

let queuePayload
try {
  const cleaned = queueOutput.replace(/^```(?:json)?\n?/m, "").replace(/\n?```$/m, "").trim()
  queuePayload = JSON.parse(cleaned)
} catch (e) {
  throw new Error(`Phase 1: failed to parse --export-queue JSON: ${e.message}\nRaw: ${queueOutput}`)
}

const skills = queuePayload.queue
const excluded = queuePayload.excluded || []
log(`Queue: ${skills.length} skill(s). Excluded: ${excluded.length}.`)
if (excluded.length > 0) {
  log(`Excluded: ${excluded.map(e => `${e.skill} (${e.reason})`).join(", ")}`)
}

if (skills.length === 0) {
  log("Queue empty — nothing to launch.")
  return { action: "empty-queue", excluded }
}

// ── Phase 2: Serial agent() per skill ─────────────────────────────────────────
// IMPORTANT: serial, NOT parallel(). Each /skill-iterate invocation needs a FRESH
// context window. Parallel() would multiplex N skills into one shared context, defeating
// the purpose of m2_launcher's serial-fresh-context design.
phase("Run skills")
log(`Running ${skills.length} skill(s) serially (fresh context per agent() call) ...`)

const results = []
const startTs = Date.now()

for (let i = 0; i < skills.length; i++) {
  const skill = skills[i]
  log(`[${i + 1}/${skills.length}] Running /skill-iterate for ${skill} ...`)
  const skillStart = Date.now()

  const skillOutput = await agent(
    `/skill-iterate --skill ${skill} --per-skill-iterations ${iters} --per-skill-budget ${budget}`,
    { label: skill, phase: "Run skills" },
  )

  const durationSeconds = (Date.now() - skillStart) / 1000
  const exitCode = 0  // agent() either returns or throws; treat as 0 on success
  const status = "ok"

  results.push({
    skill,
    exit_code: exitCode,
    duration_seconds: durationSeconds,
    status,
    log: skillOutput || "",
  })
  log(`  -> ${status} (${durationSeconds.toFixed(0)}s)`)
}

const totalSeconds = (Date.now() - startTs) / 1000
log(`All ${skills.length} skill(s) complete in ${totalSeconds.toFixed(0)}s total.`)

// ── Phase 3: Write manifest ───────────────────────────────────────────────────
phase("Write manifest")

// Write per-skill .log files and the results JSON to a temp path, then call --write-manifest.
const resultsJson = JSON.stringify(results)
const tmpResultsPath = "~\\AppData\\Local\\Temp\\m2_launcher_results.json"

const manifestOutput = await agent(
  `Do the following steps in order:

1. Write the following JSON to "${tmpResultsPath}":
${resultsJson}

2. For each of the following skills, write the corresponding "log" field to the path below:
${results.map(r => `   - Skill: ${r.skill}\n     Path: ${logsBase}\\m2-launcher-LATEST\\${r.skill}.log\n     Log content (first 500 chars shown; write the full log from the results JSON): ...`).join("\n")}

Actually, skip step 2 for the per-skill logs (those will be read from the results JSON by --write-manifest). Just do step 1, then run:

\`\`\`powershell
python "${launcherPath}" --write-manifest "${tmpResultsPath}" "${logsBase}\\m2-launcher-LATEST"
\`\`\`

Return the full output of the command verbatim.`,
  { label: "write-manifest", phase: "Write manifest" },
)

log("Manifest written.")
return {
  action: "complete",
  skills_run: skills.length,
  excluded_count: excluded.length,
  total_seconds: totalSeconds,
  manifest_output: manifestOutput,
}
