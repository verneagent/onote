#!/usr/bin/env python3
"""
Obsidian-aware markdown lint wrapper.

Uses markdownlint-cli2 with custom config that handles Obsidian-specific
syntax (callouts, wikilinks, comments, etc.).

Usage:
    python3 lint.py <file_or_dir> [--fix] [--json]

Requires: markdownlint-cli2 (npm install -g markdownlint-cli2)
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = Path.home() / ".onote" / "config.json"

# markdownlint config that plays nice with Obsidian
MARKDOWNLINT_CONFIG = {
    "default": True,
    # Disable rules that conflict with Obsidian syntax
    "MD013": False,           # Line length — Obsidian wraps visually
    "MD033": False,           # Inline HTML — Obsidian uses HTML for some features
    "MD041": False,           # First line should be top-level heading — not always true for notes
    "MD028": False,           # Blank line inside blockquote — callouts use nested blockquotes
    "MD036": False,           # Emphasis used instead of heading — common in notes
    "MD046": {"style": "fenced"},  # Code block style
}


def _load_vault_path() -> Path:
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open() as f:
            return Path(json.load(f)["vault_path"])
    raise SystemExit(f"Config not found: {CONFIG_PATH}")


def obsidian_precheck(filepath: Path) -> list[dict]:
    """Check Obsidian-specific syntax that markdownlint doesn't cover."""
    issues = []
    try:
        text = filepath.read_text(encoding="utf-8")
    except Exception as e:
        issues.append({"line": 0, "rule": "OBS001", "desc": f"Cannot read file: {e}"})
        return issues

    lines = text.split("\n")
    in_code_block = False
    code_fence_line = 0

    for i, line in enumerate(lines, 1):
        # Track code blocks (allow leading whitespace for indented fences)
        if re.match(r"^\s*(`{3,}|~{3,})", line):
            if in_code_block:
                in_code_block = False
            else:
                in_code_block = True
                code_fence_line = i
            continue

        if in_code_block:
            continue

        # OBS001: Callout syntax check
        callout_match = re.match(r"^>\s*\[!([\w-]*)\]", line)
        if callout_match:
            callout_type = callout_match.group(1)
            valid_types = {
                "note", "tip", "hint", "info", "warning", "danger",
                "error", "bug", "example", "quote", "cite",
                "success", "check", "done", "failure", "fail", "missing",
                "question", "help", "faq",
                "abstract", "summary", "tldr",
                "todo", "important", "caution", "attention",
            }
            if callout_type.lower() not in valid_types:
                issues.append({
                    "line": i, "rule": "OBS001",
                    "desc": f"Unknown callout type: [!{callout_type}]. "
                            f"Valid: {', '.join(sorted(valid_types))}",
                })

        # OBS002: Unclosed wikilink
        wikilink_opens = line.count("[[")
        wikilink_closes = line.count("]]")
        if wikilink_opens != wikilink_closes:
            issues.append({
                "line": i, "rule": "OBS002",
                "desc": f"Unclosed wikilink: {wikilink_opens} opens, {wikilink_closes} closes",
            })

        # OBS003: Unclosed inline code (odd number of backticks, excluding code blocks)
        # Remove matched inline code spans before counting
        stripped = re.sub(r"```.*?```", "", line)
        stripped = re.sub(r"``.*?``", "", stripped)
        stripped = re.sub(r"`[^`]+`", "", stripped)
        remaining_backticks = stripped.count("`")
        if remaining_backticks > 0:
            issues.append({
                "line": i, "rule": "OBS003",
                "desc": "Unpaired backtick — possible unclosed inline code",
            })

        # OBS004: Unclosed Obsidian comment
        if "%%" in line:
            comment_count = line.count("%%")
            if comment_count % 2 != 0:
                # Check if it's opened on this line and closed on another
                # (multi-line comments). Only flag if there's no matching close.
                rest_of_file = "\n".join(lines[i:])
                total_markers = rest_of_file.count("%%")
                if total_markers % 2 != 0:
                    issues.append({
                        "line": i, "rule": "OBS004",
                        "desc": "Unclosed Obsidian comment (%%)",
                    })

        # OBS005: Broken markdown link
        for m in re.finditer(r"\[([^\]]*)\]\(([^)]*$)", line):
            issues.append({
                "line": i, "rule": "OBS005",
                "desc": f"Unclosed markdown link: [{m.group(1)}](...",
            })

    # Check unclosed code block at end of file
    if in_code_block:
        issues.append({
            "line": code_fence_line, "rule": "OBS006",
            "desc": "Unclosed code block (no matching ```)",
        })

    return issues


def run_markdownlint(filepath: Path, fix: bool = False) -> list[dict]:
    """Run markdownlint-cli2 on a file and parse output."""
    # Write temp config
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".markdownlint.jsonc", delete=False
    ) as f:
        json.dump(MARKDOWNLINT_CONFIG, f)
        config_path = f.name

    try:
        cmd = ["markdownlint-cli2"]
        if fix:
            cmd.append("--fix")
        cmd.append(str(filepath))

        env = os.environ.copy()
        env["MARKDOWNLINT_CONFIG"] = config_path

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
            env=env, cwd=str(filepath.parent),
        )

        issues = []
        for line in result.stdout.splitlines() + result.stderr.splitlines():
            # Parse: filename:line:col rule/description
            m = re.match(r".*?:(\d+)(?::(\d+))?\s+(MD\d+)/(\S+)\s+(.*)", line)
            if m:
                issues.append({
                    "line": int(m.group(1)),
                    "rule": m.group(3),
                    "desc": m.group(5).strip(),
                })
        return issues
    except FileNotFoundError:
        print("Error: markdownlint-cli2 not found. Install: npm install -g markdownlint-cli2",
              file=sys.stderr)
        return []
    except subprocess.TimeoutExpired:
        print("Error: markdownlint-cli2 timed out", file=sys.stderr)
        return []
    finally:
        os.unlink(config_path)


def lint_file(filepath: Path, fix: bool = False) -> list[dict]:
    """Run all lint checks on a single file."""
    all_issues = []

    # Obsidian-specific checks
    obs_issues = obsidian_precheck(filepath)
    all_issues.extend(obs_issues)

    # Standard markdownlint
    md_issues = run_markdownlint(filepath, fix=fix)
    all_issues.extend(md_issues)

    # Sort by line number
    all_issues.sort(key=lambda x: x.get("line", 0))
    return all_issues


def lint_path(target: Path, fix: bool = False) -> dict[str, list[dict]]:
    """Lint a file or all .md files in a directory."""
    results = {}

    if target.is_file():
        issues = lint_file(target, fix=fix)
        if issues:
            results[str(target)] = issues
    elif target.is_dir():
        for md_file in sorted(target.rglob("*.md")):
            # Skip hidden dirs and .obsidian
            parts = md_file.relative_to(target).parts
            if any(p.startswith(".") or p in {"_assets"} for p in parts):
                continue
            issues = lint_file(md_file, fix=fix)
            if issues:
                results[str(md_file)] = issues
    else:
        print(f"Error: {target} not found", file=sys.stderr)
        sys.exit(1)

    return results


def main():
    parser = argparse.ArgumentParser(description="Obsidian-aware markdown linter")
    parser.add_argument("target", help="File or directory to lint")
    parser.add_argument("--fix", action="store_true", help="Auto-fix where possible")
    parser.add_argument("--json", action="store_true", dest="json_output",
                        help="Output as JSON")
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()

    # If target is relative to vault, resolve it
    if not target.exists():
        vault = _load_vault_path()
        resolved = vault / args.target
        if resolved.exists():
            target = resolved

    results = lint_path(target, fix=args.fix)

    if args.json_output:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        if not results:
            print("✓ No issues found")
        else:
            total = 0
            for filepath, issues in results.items():
                # Show relative path if possible
                try:
                    vault = _load_vault_path()
                    display = str(Path(filepath).relative_to(vault))
                except (ValueError, SystemExit):
                    display = filepath

                print(f"\n{display}")
                for issue in issues:
                    total += 1
                    line = issue.get("line", "?")
                    rule = issue.get("rule", "?")
                    desc = issue.get("desc", "")
                    print(f"  L{line}: [{rule}] {desc}")

            print(f"\n{total} issue(s) in {len(results)} file(s)")


if __name__ == "__main__":
    main()
