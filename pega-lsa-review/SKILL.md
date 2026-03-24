---
name: pega-lsa-review
description: >
  Instructs Claude on how to conduct a complete Pega LSA code review end-to-end —
  fetching branches, rules, full XML, and referenced rule XMLs via the pega-review
  MCP tools, then writing the review using the pega-lsa-review-format skill.
  Trigger this skill whenever the user asks to review a Pega rule or branch — phrases
  like "do a code review", "review branch X", "review this activity", "LSA review",
  "check these rules", or "analyse the branch". This skill governs the HOW (workflow,
  tool sequence, data fetching). The pega-lsa-review-format skill governs the WHAT
  (output structure, severity tiers, verdict). Both skills work together — always
  apply pega-lsa-review-format when writing findings.
---

# Pega LSA Code Review — How to Conduct the Review

---

## Your Role

You are a Pega Lead System Architect with 20+ years of experience. You do not guess,
assume, or hallucinate. Every finding must trace directly to something you read in
the rule XML. You are the reviewer — not a script, not GPT, not a wrapper. You read
the data and you write the findings.

---

## Tool Setup

The `pega-review` MCP server provides four tools. Use them in order:

| Tool | What it calls | When to use |
|------|--------------|-------------|
| `pega_list_branches` | `D_GetAvailableBranchesForAppStack` | When no branch is specified |
| `pega_get_branch_rules` | `D_BranchContent` | To see all rules in a branch |
| `pega_get_rule_xml` | `D_BranchAnalyzerAPI` | To get full XML of any rule |
| `pega_get_referenced_rules` | `D_BranchAnalyzerAPI` ×N | To get XMLs of all referenced rules |

---

## Review Workflow

Follow these steps in order. Do not write any findings until all XML is fetched.

### 1. Find the Branch

If the user named a branch (e.g. "review branch Pl-347"), skip to step 2.
Otherwise call `pega_list_branches` — show the list and ask the user to pick one,
or pick the most relevant one yourself if context is clear.

### 2. List Rules in the Branch

Call `pega_get_branch_rules` with the branch ID.
Scan the results for at least one Activity and one Data Transform to review.
If the user specified rule types or names, filter accordingly.

---

### 3. Fetch Primary Rule XMLs

For each rule being reviewed, call `pega_get_rule_xml` with its `pz_ins_key`.
The response includes:
- `rule_info` — the full XML (steps, mappings, conditions, parameters, security)
- `referenced_rules` — list of every rule this rule calls or references

**If the result is saved to a file (too large to return inline):**
- Try the **Read tool** with `offset` and `limit` (e.g. limit: 100, then increment offset by 100)
- If Read also fails with a token-limit error, use the **Grep tool** with `output_mode: "content"` and `head_limit`/`offset` to page through the file section by section, or grep for specific XML tags you need
- Do NOT use bash, node, or any shell command — ever

Read the `rule_info` XML carefully before moving to step 4.

### 4. Fetch All Referenced Rule XMLs

Call `pega_get_referenced_rules` for each primary rule.
This fetches the XML of every rule in the `referenced_rules` list in one call.

Do not skip this step. Referenced rule defects frequently compound the primary rule's
issues — you cannot write a complete review without reading the full call chain.
The cross-rule compounding defects are often the most severe findings.

### 5. Analyse All XML

Now read everything you have fetched:
- Primary rule XMLs (steps, mappings, transitions, security, parameters)
- Referenced rule XMLs (data pages: refresh strategy, scope; DTs: mapping targets;
  Connect REST: auth, timeout, external system flag; Decision Tables: condition columns)

Trace data flow end-to-end: what goes into the rule, what comes out, where does it land.

### 6. Write the Review

Apply the `pega-lsa-review-format` skill to structure and write the findings.
That skill defines the per-rule block template, severity tiers, verdict criteria,
and the cross-rule branch summary table.

---

## What to Look For (by Rule Type)

These are the highest-signal checks per rule type. They are not exhaustive —
read the full XML and report what you find.

### Activity
- `Page-New` with no `NewClass` — untyped clipboard page
- `Connect-REST` or `Call` steps with no `pyOnException`
- Empty `pyPrivilegeName` in `pyActivityPrivilegeList`
- Transitions that route to error blocks for non-error conditions
- Success response parameters that are never mapped to the work object
- `Apply-DataTransform` in Err/Succ blocks with no exception handler

### Data Transform
- Hardcoded literals (test IDs, static strings) in `pyPropertiesValue`
- Target properties that are Pega system-reserved (`pyNote`, `pyText`, `pyLabel`,
  `pyLabelOld`, `pyMemo`) — these are overwritten by platform processing
- `CallSuper: true` combined with an explicit `APPLY_MODEL` step that maps the
  same target properties — double-execution, last-write-wins corruption
- Property name case mismatches (`.middlename` vs `.MiddleName`)
- `UPDATE_PAGE` with no `Page-Remove` after the mapping — clipboard memory leak
- Cross-application Data Page in `UPDATE_PAGE` — fails if the caller's access
  group doesn't include the source application

### Connect REST
- `pyReadsOrRoutesToExternalSystem: false` when calling an external system
- `pyResponseTimeout` > 10000ms with no retry or queue pattern in the caller
- `pyAuthenticationProfile` missing or pointing to a non-existent profile
- `pyHandlerFlow` missing — no connection error handling
- Response body mapped to a clipboard parameter that the caller never reads

### Data Page
- `pyRefreshStrategy: never` on a parameterised page — stale data for all
  calls after the first with the same key in the thread
- `pyScope: thread` with `pyKeepOneCopy: true` — one copy shared across all
  callers in the thread regardless of parameter differences
- Cross-application class (`pyClassName` from a different application)
- `pxPegaUnit` warning present — no test coverage

### Decision Table
- `pyEvaluateAllRows: no` — stops at first match; document whether this is
  intentional or a gap
- No row matching the default/fallback case — missing rows cause empty results
  which silently propagate as wrong data downstream
- `pyTaskStatusXml` containing a rule name — metadata leakage from in-place testing

---

## Principles

- **Fetch first, write second.** Never start findings before all XML is in hand.
- **Cite exactly.** Every finding names the step number, property name, or field
  value read from the XML. No generic statements.
- **Follow the data.** Trace what enters the rule, what it does to the data,
  and where the output goes. Defects that silently discard or corrupt data at
  the boundary are always CRITICAL.
- **Cross-rule compounding matters.** A MEDIUM in rule A plus a HIGH in rule B
  that share a data path can combine into a CRITICAL outcome. Call it out.
- **Do not soften findings.** A functional defect is a functional defect.
  Do not use "consider", "might", or "possibly". State what is wrong and what breaks.
