export const meta = {
  name: 'score-skill',
  description: 'Score one or more SKILL.md versions with an independent produce/grade split: one agent RENDERS each scenario, a SEPARATE agent GRADES it (never grading its own output), and a final agent aggregates via the existing Python scorers. Variants mode adds a mutate stage. Used by /skill-evolve (variants) and /skill-iterate (single version per iteration).',
  phases: [
    { title: 'Load', detail: 'read evals.json + scenario ids/expected_assertions' },
    { title: 'Mutate', detail: 'variants mode only: apply each strategy to a fresh SKILL.md copy' },
    { title: 'Render', detail: 'one agent per (version, scenario) simulates the skill output' },
    { title: 'Grade', detail: 'a SEPARATE agent grades each rendered output (produce/grade split)' },
    { title: 'Score', detail: 'aggregate verdicts via score_skill_composite.py + score_skill_absolute.py' },
  ],
}

// ---------------------------------------------------------------------------
// WHY THIS IS A WORKFLOW AND NOT A SUB-AGENT
//
// The bug this replaces: a single sub-agent was told to BOTH simulate a skill's
// output AND grade that same output. A grader that just produced the artifact is
// biased toward it — and a sub-agent cannot spawn its own producer/grader
// sub-agents to fix that (agent nesting is depth-1). The orchestration therefore
// HAS to live one level up. Here, the workflow script is that level: it spawns a
// render agent and a DIFFERENT grade agent as siblings. The grade agent only ever
// sees a file the render agent wrote — it never produced what it grades.
//
// Division of labour:
//   - This script: control flow only (fan-out, trials, which agent runs when).
//     It has NO filesystem / shell / git access.
//   - Agents: all file writes, Python calls, and reads. They have tools.
//   - Python (score_skill_composite.py / score_skill_absolute.py): the single
//     source of truth for the actual score math. We never re-implement it here.
//
// args contract:
//   {
//     shared_dir: "<abs path to .claude/skills/_shared>",   // home of the .py scorers + grader_prompt.py
//     work_dir:   "<abs writable temp dir>",                 // agents write render/verdict/payload artifacts here
//     evals_dir:  "<abs path to the skill's evals/ dir>",    // evals are NOT mutated; shared across versions
//     trials:     1,                                         // grade-rounds per scenario (saturation handler passes 3)
//     // exactly ONE of:
//     versions:  [{ id, label, skill_md_path }],                  // score these on-disk SKILL.md files as-is
//     variants:  [{ id, label, strategy, base_skill_md_path }],   // mutate the base per strategy, THEN score
//   }
//
// returns: one result object per version/variant:
//   { id, label, skill_md_path, score, passed, total, status, failed_assertions, passing_pairs }
// ---------------------------------------------------------------------------

const RENDER_SCHEMA = {
  type: 'object',
  required: ['scenario_id', 'render_path'],
  properties: {
    scenario_id: { type: 'string' },
    render_path: { type: 'string' },
  },
}

const GRADE_SCHEMA = {
  type: 'object',
  required: ['scenario_id', 'verdicts_path'],
  properties: {
    scenario_id: { type: 'string' },
    verdicts_path: { type: 'string' },
  },
}

const MUTATE_SCHEMA = {
  type: 'object',
  required: ['id', 'skill_md_path'],
  properties: {
    id: { type: 'string' },
    skill_md_path: { type: 'string' },
  },
}

const LOAD_SCHEMA = {
  type: 'object',
  required: ['evals_path', 'scenarios_path', 'scenarios'],
  properties: {
    evals_path: { type: 'string' },
    scenarios_path: { type: 'string' },
    scenarios: {
      type: 'array',
      items: {
        type: 'object',
        required: ['id', 'expected_assertions'],
        properties: {
          id: { type: 'string' },
          expected_assertions: { type: 'array', items: { type: 'number' } },
        },
      },
    },
  },
}

const AGG_SCHEMA = {
  type: 'object',
  required: ['score', 'passed', 'total', 'status'],
  properties: {
    score: { type: ['number', 'null'] },
    passed: { type: 'number' },
    total: { type: 'number' },
    status: { type: 'string' },
    failed_assertions: { type: 'array' },
    passing_pairs: { type: 'array' },
  },
}

const shared_dir = args.shared_dir
const work_dir = args.work_dir
const evals_dir = args.evals_dir
const trials = args.trials && args.trials > 0 ? args.trials : 1
const versions = args.versions || null
const variants = args.variants || null

if (!shared_dir || !work_dir || !evals_dir) {
  throw new Error('score-skill: args.shared_dir, args.work_dir and args.evals_dir are all required')
}
if ((!versions && !variants) || (versions && variants)) {
  throw new Error('score-skill: pass exactly one of args.versions or args.variants')
}

function loadPrompt() {
  return [
    'You are reading eval config for a skill-scoring run. Do not grade or render anything.',
    `evals.json lives at: ${evals_dir}/evals.json`,
    `test_scenarios.json lives at: ${evals_dir}/test_scenarios.json`,
    'Read test_scenarios.json. For each scenario return its "id" and its "expected_assertions" array',
    '(use an empty array if the scenario has no expected_assertions field).',
    'Return evals_path (absolute path to evals.json), scenarios_path (absolute path to test_scenarios.json),',
    'and the scenarios array. Do NOT return scenario "context" bodies — later agents read those directly.',
  ].join('\n')
}

function mutatePrompt(v) {
  const out = `${work_dir}/variant_${v.id}.SKILL.md`
  return {
    out,
    prompt: [
      'You apply ONE mutation strategy to a SKILL.md and then STOP.',
      'You do NOT evaluate, score, render, or grade anything — a separate agent scores your result later.',
      `Read the baseline skill definition at: ${v.base_skill_md_path}`,
      `Apply this strategy, interpreted literally, as a SINGLE pass: "${v.strategy}"`,
      'Change only what the strategy calls for; leave every other rule intact.',
      `Write the FULL mutated SKILL.md (entire file, not a diff) to a NEW file at: ${out}`,
      `Do NOT modify the baseline file at ${v.base_skill_md_path}.`,
      `Return { "id": "${v.id}", "skill_md_path": "${out}" }.`,
    ].join('\n'),
  }
}

function renderPrompt(vid, skill_md_path, scenario, scenarios_path) {
  const render_path = `${work_dir}/render_${vid}_${scenario.id}.md`
  return {
    render_path,
    prompt: [
      'You PRODUCE a skill output. You do NOT grade it — a different agent will.',
      `Read the skill definition at: ${skill_md_path}`,
      `Read ${scenarios_path}, find the scenario whose id is "${scenario.id}", and use its "context" field as the input environment.`,
      'Execute the SKILL.md instructions exactly as if you were running that skill against that scenario context,',
      'and produce the full output the skill would generate for this scenario.',
      `Write ONLY that produced output (no preamble, no commentary, no fences around the whole thing) to: ${render_path}`,
      `Return { "scenario_id": "${scenario.id}", "render_path": "${render_path}" }.`,
    ].join('\n'),
  }
}

function gradePrompt(vid, scenario, render_path, evals_path, trial) {
  const verdicts_path = `${work_dir}/verdicts_${vid}_${scenario.id}_t${trial}.json`
  const expected = '[' + (scenario.expected_assertions || []).join(', ') + ']'
  return {
    verdicts_path,
    prompt: [
      'You are a STRICT grader. You did NOT produce the artifact you are grading; do not be charitable to it.',
      'Build your exact grading instructions from the canonical helper — do not invent or paraphrase your own rubric.',
      `The helper is build_grader_prompt in ${shared_dir}/grader_prompt.py.`,
      'Run Python to print the canonical prompt, e.g.:',
      `  python -c "import sys; sys.path.insert(0, r'${shared_dir}'); from grader_prompt import build_grader_prompt; ` +
        `print(build_grader_prompt(scenario_id=r'${scenario.id}', ` +
        `rendered_output=open(r'${render_path}', encoding='utf-8').read(), ` +
        `evals_json=open(r'${evals_path}', encoding='utf-8').read(), ` +
        `expected_assertions=${expected}))"`,
      'Follow the printed instructions verbatim against the rendered output. Grade every assertion id in evals.json.',
      `Write your result as JSON of EXACT shape {"verdicts": {"<id>": {"verdict": true|false, "reason": "..."}}} to: ${verdicts_path}`,
      `Return { "scenario_id": "${scenario.id}", "verdicts_path": "${verdicts_path}" }.`,
    ].join('\n'),
  }
}

function aggregatePrompt(vid, skill_md_path, evals_path, verdictRefs) {
  const payload_path = `${work_dir}/payload_${vid}.json`
  return [
    'You assemble a verdict payload and run the canonical Python scorers. Do not invent scores.',
    `Verdict files (one per (scenario, trial)) as JSON pairs: ${JSON.stringify(verdictRefs)}`,
    `evals.json: ${evals_path}`,
    `SKILL.md under evaluation: ${skill_md_path}`,
    '',
    'Step 1 — Build the payload. payload = {"trials": [ ... ]}. For each verdict file above, read its JSON',
    '(shape {"verdicts": {...}}) and append one block {"scenario_id": <its scenario_id>, "verdicts": <its verdicts dict>}.',
    'Multiple blocks may share a scenario_id (one per trial) — include them all; the aggregator collapses by majority vote.',
    '',
    'Step 2 — Repair to the aggregator contract: for every assertion id in evals.json that is missing from a block,',
    'backfill {"verdict": false, "reason": "grader omitted"}. Drop any verdict id NOT present in evals.json.',
    '',
    `Step 3 — Write the payload to ${payload_path}.`,
    '',
    'Step 4 — Composite score (structural + absolute blend):',
    `  python ${shared_dir}/score_skill_composite.py --skill-md "${skill_md_path}" --baseline "${skill_md_path}" ` +
      `--modified "${skill_md_path}" --mode composite --absolute-verdicts "${payload_path}" --evals "${evals_path}"`,
    '  Parse its JSON; take score, passed, total, status.',
    '',
    'Step 5 — Failure detail (for brainstorm targeting):',
    `  python ${shared_dir}/score_skill_absolute.py --evals "${evals_path}" --input "${payload_path}"`,
    '  Parse its JSON; take failed_assertions and passing_pairs.',
    '',
    'Return { "score", "passed", "total", "status", "failed_assertions", "passing_pairs" } merging both outputs.',
    'If a scorer errors, return status="harness-error" with score=null and echo the stderr in failed_assertions[0].',
  ].join('\n')
}

async function scoreVersion(version, scenarios, scenarios_path, evals_path) {
  const { id, label, skill_md_path } = version

  if (!scenarios.length) {
    log(`score-skill: ${id} has no scenarios — cannot grade`)
    return { id, label, skill_md_path, score: null, passed: 0, total: 0, status: 'harness-error', failed_assertions: [], passing_pairs: [] }
  }

  // Per scenario: render ONCE, then grade `trials` times. Render and grade are
  // distinct agents — the grade agent only reads the file the render agent wrote.
  const perScenario = await parallel(
    scenarios.map((sc) => () => {
      const r = renderPrompt(id, skill_md_path, sc, scenarios_path)
      return agent(r.prompt, { label: `render:${id}:${sc.id}`, phase: 'Render', schema: RENDER_SCHEMA }).then((rendered) => {
        const render_path = rendered ? rendered.render_path : r.render_path
        const trialThunks = Array.from({ length: trials }, (_, t) => () => {
          const g = gradePrompt(id, sc, render_path, evals_path, t)
          return agent(g.prompt, { label: `grade:${id}:${sc.id}:t${t}`, phase: 'Grade', schema: GRADE_SCHEMA }).then((graded) => ({
            scenario_id: sc.id,
            verdicts_path: graded ? graded.verdicts_path : g.verdicts_path,
          }))
        })
        return parallel(trialThunks).then((grades) => grades.filter(Boolean))
      })
    })
  )

  const verdictRefs = perScenario.filter(Boolean).flat()
  const agg = await agent(aggregatePrompt(id, skill_md_path, evals_path, verdictRefs), {
    label: `aggregate:${id}`,
    phase: 'Score',
    schema: AGG_SCHEMA,
  })
  if (!agg) {
    return { id, label, skill_md_path, score: null, passed: 0, total: 0, status: 'harness-error', failed_assertions: [], passing_pairs: [] }
  }
  return {
    id,
    label,
    skill_md_path,
    score: agg.score,
    passed: agg.passed,
    total: agg.total,
    status: agg.status,
    failed_assertions: agg.failed_assertions || [],
    passing_pairs: agg.passing_pairs || [],
  }
}

phase('Load')
log(`score-skill: loading scenarios from ${evals_dir}`)
const loaded = await agent(loadPrompt(), { label: 'load-evals-scenarios', phase: 'Load', schema: LOAD_SCHEMA })
const scenarios = loaded.scenarios || []
const evals_path = loaded.evals_path
const scenarios_path = loaded.scenarios_path
log(`score-skill: ${scenarios.length} scenario(s); trials=${trials}`)

let results
if (variants) {
  // Mutate each variant into its own SKILL.md copy, THEN score it. Mutation and
  // scoring are separate agents; the scorer never sees the mutation strategy.
  results = await parallel(
    variants.map((v) => () => {
      const m = mutatePrompt(v)
      return agent(m.prompt, { label: `mutate:${v.id}`, phase: 'Mutate', schema: MUTATE_SCHEMA }).then((mutated) =>
        scoreVersion(
          { id: v.id, label: v.label || v.id, skill_md_path: mutated ? mutated.skill_md_path : m.out },
          scenarios,
          scenarios_path,
          evals_path
        )
      )
    })
  )
} else {
  results = await parallel(versions.map((v) => () => scoreVersion({ id: v.id, label: v.label || v.id, skill_md_path: v.skill_md_path }, scenarios, scenarios_path, evals_path)))
}

return results.filter(Boolean)
