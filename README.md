# onote

An AI agent skill for capturing notes and TODOs into an [Obsidian](https://obsidian.md/) vault organized with the [PARA method](https://fortelabs.com/blog/para/).

## Requirements

- An Obsidian vault with the PARA folder structure:

  ```
  vault/
  ├── 🚧 Projects/
  ├── 🤹‍♀️ Areas/
  ├── 📚 Resources/
  ├── ✏️ Quick Notes/
  └── ✅ TODOs/
      ├── work.md
      └── life.md
  ```

- Python 3.10+
- A Claude Code / OpenCode / Codex agent that supports skills

## Setup

Create `~/.onote/config.json` with your vault path:

```json
{
  "vault_path": "/path/to/your/obsidian/vault"
}
```

Optional fields:

| Key | Default | Description |
|-----|---------|-------------|
| `cache_dir` | `~/.onote/cache` | Where the local routing index is stored |

## Install

```bash
npx skills add -g verneagent/onote
```

## Usage

Trigger with the exact lowercase word `onote` followed by a subcommand:

```
onote project <title or intent>
onote area <title or intent>
onote resource <title or intent>
onote quick <title or intent>
onote todo <work|life> <todo text>
onote sync [project|area|resource|all]
```

### Subcommands

| Command | Purpose | PARA bucket |
|---------|---------|-------------|
| `project` | Active project notes, decisions, plans | Projects |
| `area` | Durable knowledge, workflows, methods | Areas |
| `resource` | Reference material, guides, account info | Resources |
| `quick` | Quick inbox capture for unclassified notes | Quick Notes |
| `todo` | Append a checkbox item to a TODO list | TODOs |
| `sync` | Rebuild the local routing index | — |

### How routing works

When you save a note, onote automatically picks the best subfolder within the target PARA bucket:

1. Scans existing notes and builds a lightweight local embedding index (pure offline, no API calls)
2. Matches your note's title and content against the index using a combination of lexical overlap and vector similarity
3. Uses folder-name matching as a tie-breaker

The index is stored in SQLite with compact float vectors — fast and low disk usage.

## License

MIT
