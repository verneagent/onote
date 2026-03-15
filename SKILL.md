---
name: onote
description: "Save a note or TODO into an Obsidian vault. Trigger only when the user explicitly includes the exact lowercase word `onote`, and require a subcommand: `project`, `area`, `resource`, `quick`, or `todo`."
---

# Onote

## Setup

This skill requires `~/.onote/config.json` with machine-specific settings:

```json
{
  "vault_path": "/path/to/your/obsidian/vault",
  "cache_dir": "~/.onote/cache"
}
```

- `vault_path` (required): absolute path to the Obsidian vault
- `cache_dir` (optional): where the routing index is stored (defaults to `~/.onote/cache`)

Use this skill only when the user message explicitly contains the exact lowercase standalone word `onote`.

## Trigger rule

- Trigger only on the exact lowercase token `onote`
- Accept `onote <subcmd> ...` and `/onote <subcmd> ...`
- Do not trigger on `Onote`, `ONOTE`, `oNote`, or natural-language requests like "记一下", "save this", or "jot this down"
- Do not infer intent from context alone
- A valid subcommand is required. Supported subcommands are `project`, `area`, `resource`, `quick`, `todo`, `sync`, and `lint`
- There is no `archive` mode anymore

When triggered, capture content into the Obsidian vault configured in `~/.onote/config.json` (`vault_path` key).

## Command forms

User-facing forms:
- `onote project <title or intent>`
- `onote area <title or intent>`
- `onote resource <title or intent>`
- `onote quick <title or intent>`
- `onote todo <work|life> <todo text>`
- `onote sync [project|area|resource|all]`
- `onote lint <file_or_dir>` — lint markdown for Obsidian-specific issues

The user should only need these subcommands. Do not ask them to remember low-level script flags like `--reindex`.

Use the surrounding conversation as source material. Do not save only the literal tail of the command when the recent context already contains the real substance.

## Capture rule

`onote` should capture the relevant context mentioned around the command, not just the command text itself.

- Pull in the concrete facts, decisions, examples, tradeoffs, or definitions from the current conversation
- Compress and clean them into a readable note instead of dumping the whole transcript
- Keep the note scoped to the requested subcommand
- If the user provides almost no context, save only the explicit text they gave

## Title rule

The note title becomes the filename, so keep it short and clean.

Required behavior:
- Prefer concise subject-style titles
- Do not append suffixes like `note`, `notes`, `memo`, or similar filler words
- Use the topic itself as the title whenever possible
- Favor simple names such as `ECS、Fargate 与 EC2` over `ECS Fargate and EC2 notes`

## Subcommand meanings

### `project`

Use for notes tied to the current active project or a finite outcome.

Good fits:
- project decisions
- implementation notes
- rollout checklists
- bug investigations
- plans for the current repo or initiative

Project notes should read like working records for an active effort.

### `area`

Use for durable knowledge or operating guidance inside an ongoing responsibility area.

Good fits:
- technical methods
- repeated workflows
- principles
- operational knowledge you expect to revisit

Area notes should be knowledge-oriented, not a transient project log.

### `resource`

Use for reference material and lookup knowledge.

The existing `📚 Resources` vault currently contains material like:
- APIs and service notes
- communication / account / proxy / connectivity references
- device and equipment notes
- purchase and license records
- setup instructions and evergreen reference docs

Prefer `resource` for reusable reference material, vendor facts, setup facts, account facts, device facts, or buying/reference knowledge.

### `quick`

Use for inbox capture when the user clearly wants a note saved but the material is too rough, too short, or not worth classifying more deeply.

### `todo`

Use for actionable checklist items.

Rules:
- Syntax: `onote todo <work|life> <todo text>`
- Append a checkbox line to the corresponding TODO file instead of creating a standalone markdown note
- `work` goes to `✅ TODOs/work.md`
- `life` goes to `✅ TODOs/life.md`
- Use nearby context only to clarify the task text; keep the final line concise and actionable

## Lint subcommand

`onote lint` checks Obsidian markdown files for syntax issues that standard linters miss.

### Usage

```bash
python3 scripts/lint.py <file_or_dir> [--fix] [--json]
```

- `<file_or_dir>`: a `.md` file or a directory (lints all `.md` files recursively)
- `--fix`: auto-fix standard markdownlint issues (Obsidian-specific issues are report-only)
- `--json`: output results as JSON

### Checks

**Obsidian-specific (OBS rules):**
- `OBS001`: Unknown callout type (`> [!bogus]`)
- `OBS002`: Unclosed wikilink (`[[broken`)
- `OBS003`: Unpaired backtick (unclosed inline code)
- `OBS004`: Unclosed Obsidian comment (`%%`)
- `OBS005`: Unclosed markdown link (`[text](url` missing `)`)
- `OBS006`: Unclosed code block (no matching `` ``` ``)

**Standard markdown (MD rules via markdownlint-cli2):**
- Uses markdownlint with Obsidian-friendly defaults (disabled: MD013 line length, MD033 inline HTML, MD041 first heading, MD028 blank in blockquote)

### Requirements

- `markdownlint-cli2` must be installed globally: `npm install -g markdownlint-cli2`
- No confirmation needed — lint is read-only (unless `--fix` is passed)

## Local embedding router

`onote` now uses a pure local routing index for `project`, `area`, and `resource` notes.

Properties:
- fully offline
- no external API calls
- low disk usage via SQLite + compact float vectors
- fast enough for daily note capture

How it works:
1. It scans existing notes in the target bucket.
2. It builds lightweight local embeddings from title, summary, and folder path.
3. It stores the index in the cache directory (`~/.onote/cache/` by default, configurable via `cache_dir` in `~/.onote/config.json`).
4. Normal `project / area / resource` capture automatically refreshes the target bucket before routing, so manually added notes are picked up on the next relevant save.
5. `onote sync` is available when an explicit refresh is needed, but it should be treated as maintenance, not the default user workflow.
6. Folder-name matching is still used as a tie-breaker and fallback.
7. The router strips emoji-style prefixes from folder names, expands known aliases such as `⚛️RN -> React Native / Expo / iOS / Android`, and prefers a matching top-level branch before drilling into subfolders.

This is not a cloud model and does not download a large embedding model. It is a lightweight local semantic-ish router designed for speed and low disk usage.

## Confirmation rule

Before any write operation, `onote` must ask for confirmation in the conversation.

This applies to every write-producing subcommand:
- `project`
- `area`
- `resource`
- `quick`
- `todo`

Required behavior:
- First prepare the proposed note or TODO from context
- Then ask for confirmation before running `onote.py`
- Do not create or append any file until the user clearly confirms
- `sync` is maintenance and does not create a note, so it does not need this confirmation rule unless it would also write note content

## Workflow

1. Parse the subcommand.
2. Identify the relevant surrounding context to capture.
3. Derive a short, specific title for `project`, `area`, `resource`, or `quick`.
4. Draft a compact markdown body from the relevant context.
5. Do not repeat the note title in the body. The filename already serves as the title, so the body should start directly with the actual content.
6. Ask the user for confirmation before any write.
7. After confirmation, run `scripts/onote.py` with the explicit bucket matching the subcommand.
8. For `todo`, after confirmation, run the same script in `todo` mode and append the checkbox item to the correct list.
9. Tell the user where the note or TODO was saved and why.

## Routing guidance

Use the real subcommands directly:

- `project` -> `python3 ... onote.py project ...`
- `area` -> `python3 ... onote.py area ...`
- `resource` -> `python3 ... onote.py resource ...`
- `quick` -> `python3 ... onote.py quick ...`
- `todo` -> `python3 ... onote.py todo work|life ...`

When a specific folder is obvious, still pass `--folder-hint` because it improves routing.

### Choosing the right folder-hint

Use the **most specific matching subfolder name**, not just the top-level category:
- Bad: `--folder-hint '✨AI'` for a note about Claude Code (too broad, router may pick wrong subfolder)
- Good: `--folder-hint 'CLAUDE'` for a note about Claude Code (matches the exact subfolder)

When unsure which subfolder exists, run `ls` on the target bucket's relevant subdirectory to discover subfolder names before choosing a hint. A precise hint dramatically improves routing accuracy.

Useful maintenance command behind the scenes:

```bash
python3 scripts/onote.py sync all
```

## Command patterns

Standard note:

```bash
python3 scripts/onote.py area \
  --title 'OLU multi-agent rollout notes' \
  --content-file /tmp/onote-body.md \
  --folder-hint '✨AI'
```

TODO:

```bash
python3 scripts/onote.py todo work \
  --content 'Refactor workspace agent conversations onto the new schema'
```

## Output handling

The script prints JSON with:

- `path`: final note path
- `relative_path`: path relative to the MarkNote vault root
- `relative_folder`: folder path relative to the MarkNote vault root
- `breadcrumb`: user-facing folder breadcrumb such as `🤹‍♀️ Areas -> ⚙️技术 -> ✨AI`
- `bucket`: chosen mode
- `folder`: chosen folder or todo directory
- `reason`: why it routed there
- `created`: whether content was written
- `index`: local embedding index path

After every successful `onote` save, report the destination back to the user briefly and explicitly.
Prefer the relative folder breadcrumb first, for example `🤹‍♀️ Areas -> ⚙️技术 -> ✨AI`, and include the relative file path when useful.

Never skip the pre-write confirmation step.
