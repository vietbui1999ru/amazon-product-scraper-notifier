# Review Council

Orchestrate the review council for the current session's changes. Run after code-writer completes or when /verify is invoked.

## Step 1: Gather context

Run these commands and note the output:

```bash
# Changed files
git diff --name-only HEAD

# Active task
cat .agents/tasks.md 2>/dev/null || echo "no tasks file"

# Most relevant spec: match keyword from tasks.md, else most recent
ls -t docs/superpowers/specs/*.md 2>/dev/null | head -3
```

Read the most relevant spec file content.

## Step 2: Create review directory

```bash
REVIEW_DIR=".review/$(date +%Y-%m-%d-%H%M)"
mkdir -p "$REVIEW_DIR"
echo "Review dir: $REVIEW_DIR"
```

Substitute the actual timestamp path everywhere `<review-dir>` appears below.

## Step 3: Phase 1 — Dispatch 5 parallel background subagents

Dispatch ALL FIVE simultaneously as background subagents (run_in_background: true).

**Important:** `code-reviewer` and `architecture-reviewer` have `disallowedTools: Write` — they return text only. All Phase 1 agents return text. The orchestrating session (you) writes all Phase 1 output files in Step 4.

Give each agent a prompt containing:
- The changed files list
- The active task description
- The spec content (or "none available")
- Its specific instruction below

**code-reviewer prompt suffix:**
"Review the changed files for correctness, security, performance, and maintainability. Return your full review report as text."

**architecture-reviewer prompt suffix:**
"Review the changed files for structural coherence, coupling, scalability, and hidden risks. Return your full review report as text."

**workflow-reviewer prompt suffix:**
"Check AGENTS.md compliance for this session. Review workflow gates, skill discipline, .agents/ currency, and commit hygiene. Return your report as text."

**discrepancy-detector prompt suffix:**
"Find gaps between the spec/task and the implementation. Check for TODO(human) remaining, missing features, and interface inconsistencies. Return your report as text."

**testing-reviewer prompt suffix:**
"Assess test coverage and quality for the changed files. Check for missing tests, weak assertions, missing edge cases, and TDD compliance. Return your report as text."

Wait for all five to complete.

## Step 4: Write Phase 1 outputs

For each completed subagent, write its output text to the review directory.
You (the orchestrating session) write these files — agents return text only:

- code-reviewer output → `<review-dir>/code-review.md`
- architecture-reviewer output → `<review-dir>/architecture-review.md`
- workflow-reviewer output → `<review-dir>/workflow-review.md`
- discrepancy-detector output → `<review-dir>/discrepancy.md`
- testing-reviewer output → `<review-dir>/testing-review.md`

For any agent that failed or timed out, write a placeholder:
```
## <Role> Review
[Agent did not complete — output missing]
### Verdict: UNKNOWN
```

## Step 5: Phase 2 — Devil's advocate (foreground)

Dispatch `devil-advocate` as a foreground subagent with:

```
Review directory: <review-dir>

Read and challenge all five Phase 1 reports:
- <review-dir>/code-review.md
- <review-dir>/architecture-review.md
- <review-dir>/workflow-review.md
- <review-dir>/discrepancy.md
- <review-dir>/testing-review.md

Return your devil's advocate report as text.
```

Capture output and write to `<review-dir>/devil-advocate.md`.

## Step 6: Phase 3 — Council reporter (foreground)

Dispatch `council-reporter` as a foreground subagent with:

```
Review directory: <review-dir>
Decisions file: .agents/decisions.md

Synthesize all six review files:
- <review-dir>/code-review.md
- <review-dir>/architecture-review.md
- <review-dir>/workflow-review.md
- <review-dir>/discrepancy.md
- <review-dir>/testing-review.md
- <review-dir>/devil-advocate.md

Write your report to <review-dir>/report.md
Append qualifying architectural decisions to .agents/decisions.md
```

## Step 7: Surface summary

Read `<review-dir>/report.md` and output to terminal:
- The Verdict line
- All Blockers (if any)
- The Next step line

Then output: "Full report: `<review-dir>/report.md`"
