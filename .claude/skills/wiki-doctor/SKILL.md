---
name: wiki-doctor
description: Use when the user asks for a health check, lint, audit, or wants to check for orphan pages, contradictions, or data gaps in the Wiki.
---

# Knowledge Base - Health Check

## Step 1: Broken link check (automatic)

Run this command first — it auto-fixes trivial WikiLink mismatches and reports what remains broken:

```bash
python3 scripts/wiki-doctor.py --output json --fix-simple-errors --batch-mode
python3 scripts/wiki-doctor.py --output json --fix-orphans --batch-mode
```

- `--fix-simple-errors` repairs WikiLinks where a unique normalized match exists (e.g. colons vs underscores in filenames). These are applied immediately without requiring user confirmation.
- `--fix-orphans` repairs orphaned pages by replacing matching plain text WikiLink names in files with an actual link.
- Report how many links were fixed, and list any remaining broken links for the user to review manually.
- If there are problems left, suggest the user to run:
```bash
python3 scripts/wiki-doctor.py
```

## Step 2: Report stubs

Use this command to scan markdown files for stubs:
```bash
find wiki -name "*.md" -exec awk '/^---/{p++} p==1{print FILENAME": "$0} p==2{p=0; nextfile}' {} + | grep "stub:.*true"
```
If any exist, list them in a "Stubs still needing expansion" section so the user knows what gaps remain.

## Step 3: Report known contradictions

Use this command to scan markdown files for known contradictions:
```bash
find wiki -name "*.md" -exec awk '/^---/{p++} p==1{print FILENAME": "$0} p==2{p=0; nextfile}' {} + | grep "contradiction:.*true"
```
If any exist, list them in a "Contradictions that still need resolution" section so the user knows what gaps remain.

## Step 4: Supersession check + review queue

Run the supersession lint:
```bash
python3 scripts/system/wiki-supersession-lint.py
```
- **Integrity** — report any dangling `superseded_by` targets, ambiguous targets, missing reciprocal `supersedes` back-links, or cycles. These should be fixed (the successor must exist and link back).
- **Review queue** — it writes `.import/supersession-candidates.md`: pages whose body says they were superseded/replaced/decommissioned but have no `superseded_by` field yet, with a guessed successor where one was found. Point the user to it. Do NOT auto-apply — each needs confirmation, then add `superseded_by` to the old page and reciprocal `supersedes` to the successor (see `wiki-templates`).

## Step 5: Manual checks

Present recommendations only — never modify the Wiki for these without user confirmation.

- **Missing top-level topics** — if 10+ pages relate to a common concept not listed as a top-level topic in `wiki/index.md`, suggest adding it.
- **Data gaps** — suggest new sources worth finding.
- **Missing dedicated pages** — topics mentioned across multiple pages that lack their own page; do not suggest-top-level topics, but pages within the top-level topics only.
