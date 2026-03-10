#!/usr/bin/env python3
import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
from array import array
from datetime import datetime
from pathlib import Path
from typing import Iterable


CONFIG_PATH = Path.home() / ".onote" / "config.json"


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise SystemExit(
            f"Config not found: {CONFIG_PATH}\n"
            "Create it with at least: {\"vault_path\": \"/path/to/vault\"}"
        )
    with CONFIG_PATH.open(encoding="utf-8") as f:
        return json.load(f)


_config = _load_config()
VAULT = Path(_config["vault_path"])
CACHE_DIR = Path(_config.get("cache_dir", str(Path.home() / ".onote" / "cache")))

BUCKETS = {
    "project": "🚧 Projects",
    "area": "🤹‍♀️ Areas",
    "resource": "📚 Resources",
    "quick": "✏️ Quick Notes",
    "todo": "✅ TODOs",
}
NOTE_BUCKETS = ("project", "area", "resource", "quick")
TODO_FILES = {
    "work": VAULT / BUCKETS["todo"] / "work.md",
    "life": VAULT / BUCKETS["todo"] / "life.md",
}
INDEX_DB = CACHE_DIR / "onote_index.sqlite3"
EMBED_DIM = 256
EMBED_VERSION = 2
MAX_SUMMARY_CHARS = 1200
MAX_NOTE_COUNT = 12000
IGNORED_DIRS = {"_assets", ".obsidian"}
IGNORED_FILES = {".DS_Store"}
TOPIC_KEYWORDS = {
    "project": {"project", "milestone", "launch", "ship", "deadline", "build", "fix", "plan", "decision", "rollout", "bug"},
    "area": {"health", "finance", "parenting", "method", "practice", "routine", "system", "learning", "language", "knowledge", "workflow"},
    "resource": {"reference", "snippet", "guide", "research", "article", "material", "buying", "bookmark", "api", "account", "device", "service", "setup"},
}
TOPIC_KEYWORDS_ZH = {
    "project": {"项目", "计划", "任务", "迭代", "上线", "修复", "旅行", "记录", "决策", "排查"},
    "area": {"健康", "财务", "育儿", "方法", "技术", "学习", "语言", "生活", "医疗", "运动", "知识", "流程"},
    "resource": {"资料", "参考", "教程", "文章", "摘录", "购买", "设备", "服务", "通信", "知识", "账号", "配置", "接口"},
}
TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]")
DIRECTORY_ALIASES = {
    "rn": ("react native", "react-native", "expo", "ios", "android", "mobile", "app"),
    "reactnative": ("react native", "react-native", "expo", "ios", "android", "mobile", "app"),
    "ai": ("llm", "agent", "multi agent", "multi-agent", "langgraph", "openai", "prompt"),
}


def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[_\-/]+", " ", text)
    text = re.sub(r"[^\w\s\u4e00-\u9fff]+", " ", text)
    return " ".join(text.split())


def strip_nonsemantic(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[_\-/]+", " ", text)
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff\s]+", " ", text)
    return " ".join(text.split())


def tokenize_words(text: str) -> list[str]:
    return TOKEN_RE.findall(normalize(text))


def tokenize(text: str) -> set[str]:
    return set(tokenize_words(text))


def lexical_units(text: str) -> set[str]:
    norm = normalize(text)
    units = {token for token in tokenize_words(norm) if len(token) >= 2}
    compact = norm.replace(" ", "")
    for n in (2, 3):
        if len(compact) < n:
            continue
        for idx in range(len(compact) - n + 1):
            gram = compact[idx:idx + n]
            if all("\u4e00" <= ch <= "\u9fff" for ch in gram):
                units.add(gram)
    return units


def alias_terms_for_part(part: str) -> set[str]:
    cleaned = strip_nonsemantic(part)
    compact = cleaned.replace(" ", "")
    aliases = {token for token in (cleaned, compact) if token}
    for key, values in DIRECTORY_ALIASES.items():
        if cleaned == key or compact == key or cleaned.replace(" ", "") == key:
            aliases.update(values)
    return aliases


def path_alias_text(path: Path) -> str:
    alias_chunks: list[str] = []
    for part in path.parts:
        alias_chunks.extend(sorted(alias_terms_for_part(part)))
    return " ".join(alias_chunks)


def char_ngrams(text: str, min_n: int = 2, max_n: int = 4) -> Iterable[str]:
    compact = normalize(text).replace(" ", "")
    limit = len(compact)
    for n in range(min_n, max_n + 1):
        if limit < n:
            continue
        for idx in range(limit - n + 1):
            yield compact[idx:idx + n]


def stable_hash(text: str) -> int:
    return int.from_bytes(hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest(), "big")


def text_to_embedding(*parts: str) -> list[float]:
    vec = [0.0] * EMBED_DIM
    weighted_parts = []
    for idx, part in enumerate(parts):
        if not part:
            continue
        weighted_parts.append((part, 1.8 if idx == 0 else 1.0))

    for text, base_weight in weighted_parts:
        for token in tokenize_words(text):
            h = stable_hash(f"w:{token}")
            slot = h % EMBED_DIM
            sign = -1.0 if ((h >> 8) & 1) else 1.0
            vec[slot] += sign * base_weight * 1.8
        for gram in char_ngrams(text):
            h = stable_hash(f"g:{gram}")
            slot = h % EMBED_DIM
            sign = -1.0 if ((h >> 9) & 1) else 1.0
            vec[slot] += sign * base_weight * 0.45

    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return vec
    return [v / norm for v in vec]


def pack_embedding(vec: list[float]) -> bytes:
    return array("f", vec).tobytes()


def unpack_embedding(blob: bytes) -> list[float]:
    arr = array("f")
    arr.frombytes(blob)
    return list(arr)


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    return sum(a * b for a, b in zip(vec_a, vec_b))


def path_under_vault(path: Path) -> str:
    try:
        return str(path.relative_to(VAULT))
    except ValueError:
        return str(path)


def breadcrumb_under_vault(path: Path) -> str:
    try:
        rel = path.relative_to(VAULT)
    except ValueError:
        rel = path
    parts = [part for part in rel.parts if part]
    return " -> ".join(parts)


def list_candidate_dirs(bucket_key: str) -> list[Path]:
    root = VAULT / BUCKETS[bucket_key]
    if bucket_key == "quick":
        return [root]
    candidates = [root]
    for current_root, dirnames, _ in os.walk(root):
        current = Path(current_root)
        kept: list[str] = []
        for dirname in dirnames:
            if dirname.startswith(".") or dirname in IGNORED_DIRS:
                continue
            kept.append(dirname)
            candidates.append(current / dirname)
        dirnames[:] = kept
    return candidates


def choose_bucket(text: str, requested_bucket: str | None) -> tuple[str, str]:
    if requested_bucket:
        return requested_bucket, f"explicit bucket `{requested_bucket}`"

    lowered_tokens = tokenize(text)
    scores: dict[str, int] = {name: 0 for name in ("project", "area", "resource")}
    for bucket, words in TOPIC_KEYWORDS.items():
        scores[bucket] += len(lowered_tokens & words)
    for bucket, words in TOPIC_KEYWORDS_ZH.items():
        scores[bucket] += len(lowered_tokens & words)

    best_bucket = max(scores, key=scores.get)
    if scores[best_bucket] == 0:
        return "quick", "no confident note bucket signal, used Quick Notes inbox"
    return best_bucket, f"keyword match suggested `{best_bucket}`"


def score_dir_name(path: Path, text_tokens: set[str], folder_hint: str | None, title: str | None = None) -> float:
    score = 0.0
    joined = " ".join(part for part in path.parts if part)
    dir_tokens = tokenize(joined)
    alias_tokens = tokenize(path_alias_text(path))
    score += len(text_tokens & dir_tokens) * 2.5
    alias_overlap = len(text_tokens & alias_tokens)
    score += alias_overlap * 10.0
    if alias_overlap:
        score += 6.0
    # Bonus: if the note title contains a token that is a near-exact match for
    # the leaf directory name (case-insensitive), give a strong boost.  This
    # handles cases like title "Claude Code Agent Teams" matching dir "CLAUDE".
    if title:
        norm_dir = normalize(path.name)
        norm_title = normalize(title)
        if norm_dir and norm_dir in norm_title.split():
            score += 16.0
        elif norm_dir and norm_dir in norm_title:
            score += 12.0
    if folder_hint:
        hint_tokens = tokenize(folder_hint)
        score += len(hint_tokens & dir_tokens) * 5.0
        hint_alias_overlap = len(hint_tokens & alias_tokens)
        score += hint_alias_overlap * 12.0
        if hint_alias_overlap:
            score += 8.0
        if normalize(folder_hint) in normalize(path.name):
            score += 8.0
    return score


def branch_root(path: Path, bucket_root: Path) -> Path | None:
    try:
        rel_parts = path.relative_to(bucket_root).parts
    except ValueError:
        return None
    if not rel_parts:
        return None
    return bucket_root / rel_parts[0]


def ensure_db() -> sqlite3.Connection:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(INDEX_DB)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS notes (
            path TEXT PRIMARY KEY,
            bucket TEXT NOT NULL,
            folder TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            mtime REAL NOT NULL,
            size INTEGER NOT NULL,
            version INTEGER NOT NULL,
            embedding BLOB NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_notes_bucket_folder ON notes(bucket, folder)")
    return conn


def iter_note_files(bucket: str) -> Iterable[Path]:
    root = VAULT / BUCKETS[bucket]
    if not root.exists():
        return []
    count = 0
    for current_root, dirnames, filenames in os.walk(root):
        kept: list[str] = []
        for dirname in dirnames:
            if dirname.startswith(".") or dirname in IGNORED_DIRS:
                continue
            kept.append(dirname)
        dirnames[:] = kept
        for filename in filenames:
            if filename in IGNORED_FILES or filename.startswith(".") or not filename.endswith(".md"):
                continue
            count += 1
            if count > MAX_NOTE_COUNT:
                return
            yield Path(current_root) / filename


def summarize_note(path: Path) -> tuple[str, str]:
    title = path.stem
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        raw = ""
    lines = []
    total = 0
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped == title or stripped == f"# {title}":
            continue
        lines.append(stripped)
        total += len(stripped)
        if total >= MAX_SUMMARY_CHARS:
            break
    return title, "\n".join(lines)[:MAX_SUMMARY_CHARS]


def sync_bucket_index(bucket: str) -> None:
    conn = ensure_db()
    seen: set[str] = set()
    for path in list(iter_note_files(bucket) or []):
        path_str = str(path)
        seen.add(path_str)
        stat = path.stat()
        row = conn.execute("SELECT mtime, size, version FROM notes WHERE path = ?", (path_str,)).fetchone()
        if row and float(row[0]) == stat.st_mtime and int(row[1]) == stat.st_size and int(row[2]) == EMBED_VERSION:
            continue
        title, summary = summarize_note(path)
        folder = str(path.parent)
        embedding = pack_embedding(text_to_embedding(title, summary, folder, path_alias_text(Path(folder))))
        conn.execute(
            """
            INSERT INTO notes(path, bucket, folder, title, summary, mtime, size, version, embedding)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                bucket=excluded.bucket,
                folder=excluded.folder,
                title=excluded.title,
                summary=excluded.summary,
                mtime=excluded.mtime,
                size=excluded.size,
                version=excluded.version,
                embedding=excluded.embedding
            """,
            (path_str, bucket, folder, title, summary, stat.st_mtime, stat.st_size, EMBED_VERSION, embedding),
        )
    if seen:
        placeholders = ",".join("?" for _ in seen)
        conn.execute(f"DELETE FROM notes WHERE bucket = ? AND path NOT IN ({placeholders})", (bucket, *sorted(seen)))
    else:
        conn.execute("DELETE FROM notes WHERE bucket = ?", (bucket,))
    conn.commit()
    conn.close()


def choose_folder_with_embeddings(bucket: str, text: str, folder_hint: str | None, title: str | None = None) -> tuple[Path, str]:
    if bucket == "quick":
        return VAULT / BUCKETS["quick"], "explicit quick capture"

    sync_bucket_index(bucket)
    conn = ensure_db()
    rows = conn.execute("SELECT folder, title, summary, embedding FROM notes WHERE bucket = ?", (bucket,)).fetchall()
    conn.close()

    candidates = list_candidate_dirs(bucket)
    text_tokens = tokenize(text)
    query_units = lexical_units(text)
    query_ascii = {token for token in tokenize_words(text) if token.isascii() and len(token) >= 3}
    query_vec = text_to_embedding(text, folder_hint or "")

    raw_dir_scores = {path: score_dir_name(path, text_tokens, folder_hint, title) for path in candidates}
    folder_scores = {str(path): raw_dir_scores[path] for path in candidates}
    folder_examples: dict[str, list[tuple[float, str]]] = {str(path): [] for path in candidates}
    bucket_root = VAULT / BUCKETS[bucket]

    top_level_dirs = [path for path in candidates if path.parent == bucket_root]
    branch_bias_reason = ""
    if top_level_dirs:
        branch_seed_scores = {path: score_dir_name(path, text_tokens, folder_hint, title) for path in top_level_dirs}
        branch_winner = max(branch_seed_scores, key=branch_seed_scores.get)
        if branch_seed_scores[branch_winner] > 0:
            for path in candidates:
                root = branch_root(path, bucket_root)
                if root == branch_winner:
                    folder_scores[str(path)] = folder_scores.get(str(path), 0.0) + 14.0
            branch_bias_reason = f"branch-first routing favored `{branch_winner.name}`"

    direct_winner = max(raw_dir_scores, key=raw_dir_scores.get)
    direct_bias_reason = ""
    direct_lock = False
    if raw_dir_scores[direct_winner] >= 14.0:
        for path in candidates:
            if path == direct_winner or direct_winner in path.parents:
                folder_scores[str(path)] = folder_scores.get(str(path), 0.0) + 28.0
        direct_bias_reason = f"strong directory match favored `{direct_winner.name}`"
        direct_lock = True

    for folder, title, summary, embedding_blob in rows:
        folder_scores.setdefault(folder, score_dir_name(Path(folder), text_tokens, folder_hint, title))
        folder_examples.setdefault(folder, [])
        similarity = cosine_similarity(query_vec, unpack_embedding(embedding_blob))
        note_text = "\n".join((title, summary, folder, path_alias_text(Path(folder))))
        note_units = lexical_units(note_text)
        title_units = lexical_units(title)
        folder_units = lexical_units(f"{folder}\n{path_alias_text(Path(folder))}")
        note_ascii = {token for token in tokenize_words(note_text) if token.isascii() and len(token) >= 3}
        overlap = len(query_units & note_units)
        title_overlap = len(query_units & title_units)
        folder_overlap = len(query_units & folder_units)
        ascii_overlap = len(query_ascii & note_ascii)
        lexical_score = overlap * 2.8 + title_overlap * 4.5 + folder_overlap * 3.8 + ascii_overlap * 7.5
        if query_ascii and ascii_overlap == 0:
            lexical_score -= 6.0
        if similarity <= 0 and lexical_score <= 0:
            continue
        combined_score = similarity * 6.0 + lexical_score
        folder_scores[folder] += combined_score
        folder_examples[folder].append((combined_score, title))

    best_folder = max(folder_scores, key=folder_scores.get)
    best_score = folder_scores[best_folder]
    sorted_folders = sorted(folder_scores.items(), key=lambda item: item[1], reverse=True)

    reason_parts = []
    if branch_bias_reason:
        reason_parts.append(branch_bias_reason)
    if direct_bias_reason:
        reason_parts.append(direct_bias_reason)
    matches = sorted(folder_examples.get(best_folder, []), reverse=True)[:3]
    if matches:
        reason_parts.append("local embedding + lexical match favored " + ", ".join(f"`{title}` ({score:.2f})" for score, title in matches))
    else:
        reason_parts.append("embedding index had no strong note matches")

    if len(sorted_folders) > 1 and best_score - sorted_folders[1][1] < 1.5:
        lexical_winner = max(candidates, key=lambda path: score_dir_name(path, text_tokens, folder_hint, title))
        lexical_score = score_dir_name(lexical_winner, text_tokens, folder_hint, title)
        if lexical_score > 0 and str(lexical_winner) != best_folder:
            best_folder = str(lexical_winner)
            reason_parts.append(f"close scores, lexical tie-break favored `{Path(best_folder).name}`")

    if direct_lock and Path(best_folder) != direct_winner and direct_winner not in Path(best_folder).parents:
        best_folder = str(direct_winner)
        reason_parts.append(f"locked onto strong directory match `{direct_winner.name}`")

    if Path(best_folder) == bucket_root and len(candidates) > 1:
        subfolders = [path for path in candidates if path != bucket_root]
        subfolder_winner = max(subfolders, key=lambda path: folder_scores.get(str(path), 0.0))
        if folder_scores.get(str(subfolder_winner), 0.0) >= best_score - 0.8:
            best_folder = str(subfolder_winner)
            reason_parts.append(f"preferred specific subfolder `{Path(best_folder).name}` over bucket root")

    return Path(best_folder), "; ".join(reason_parts)


def sanitize_title(title: str) -> str:
    title = title.strip().replace("/", "-").replace(":", " -")
    title = re.sub(r"\s+", " ", title)
    return title[:120] or datetime.now().strftime("%Y-%m-%d %H-%M-%S")


def ensure_unique(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return path.with_name(f"{stem} {ts}{suffix}")


def normalize_heading_text(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^#{1,6}\s*", "", text)
    text = re.sub(r"^[*_`~\-\s]+|[*_`~\-\s]+$", "", text)
    text = re.sub(r"[：:]+$", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def clean_content(content: str, title: str) -> str:
    lines = content.strip().splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    normalized_title = normalize_heading_text(title)
    if lines and normalize_heading_text(lines[0]) == normalized_title:
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines.pop(0)
    return "\n".join(lines).rstrip()


def build_body(title: str, content: str) -> str:
    return f"{clean_content(content, title)}\n"


def normalize_todo_text(content: str) -> str:
    text = " ".join(line.strip() for line in content.splitlines() if line.strip())
    text = re.sub(r"\s+", " ", text).strip()
    if text.startswith("- [ ] "):
        return text[6:].strip()
    if text.startswith("[ ] "):
        return text[4:].strip()
    return text


def append_todo(todo_list: str, content: str, dry_run: bool) -> tuple[Path, bool]:
    todo_path = TODO_FILES[todo_list]
    todo_text = normalize_todo_text(content)
    if not todo_text:
        raise SystemExit("TODO content is empty")
    if not dry_run:
        todo_path.parent.mkdir(parents=True, exist_ok=True)
        needs_newline = todo_path.exists() and todo_path.stat().st_size > 0
        with todo_path.open("a", encoding="utf-8") as handle:
            if needs_newline:
                handle.write("\n")
            handle.write(f"- [ ] {todo_text}")
    return todo_path, not dry_run


def resolve_content(args: argparse.Namespace) -> str:
    if args.content_file:
        return Path(args.content_file).read_text(encoding="utf-8")
    return args.content or ""


def run_sync(target: str) -> None:
    buckets = NOTE_BUCKETS if target == "all" else (target,)
    for bucket in buckets:
        if bucket != "quick":
            sync_bucket_index(bucket)
    print(json.dumps({"reindexed": list(buckets), "index": str(INDEX_DB)}, ensure_ascii=False))


def run_todo(args: argparse.Namespace) -> None:
    content = resolve_content(args)
    if not content.strip():
        raise SystemExit("TODO content is empty")
    todo_path, created = append_todo(args.todo_list, content, args.dry_run)
    print(json.dumps({
        "path": str(todo_path),
        "relative_path": path_under_vault(todo_path),
        "relative_folder": path_under_vault(todo_path.parent),
        "breadcrumb": breadcrumb_under_vault(todo_path.parent),
        "bucket": "todo",
        "folder": str(todo_path.parent),
        "reason": f"explicit bucket `todo`; appended to `{args.todo_list}` TODO list",
        "created": created,
        "index": str(INDEX_DB),
    }, ensure_ascii=False))


def run_note(bucket: str, args: argparse.Namespace) -> None:
    if not args.title:
        raise SystemExit("--title is required for note commands")
    content = resolve_content(args)
    if not content.strip():
        raise SystemExit("Note content is empty")
    combined = "\n".join(part for part in (args.title, content, args.folder_hint or "") if part)
    folder, folder_reason = choose_folder_with_embeddings(bucket, combined, args.folder_hint, args.title)
    note_path = ensure_unique(folder / f"{sanitize_title(args.title)}.md")
    if not args.dry_run:
        folder.mkdir(parents=True, exist_ok=True)
        note_path.write_text(build_body(args.title, content), encoding="utf-8")
    print(json.dumps({
        "path": str(note_path),
        "relative_path": path_under_vault(note_path),
        "relative_folder": path_under_vault(folder),
        "breadcrumb": breadcrumb_under_vault(folder),
        "bucket": bucket,
        "folder": str(folder),
        "reason": f"explicit bucket `{bucket}`; {folder_reason}",
        "created": not args.dry_run,
        "index": str(INDEX_DB),
    }, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="subcmd", required=True)

    sync_parser = subparsers.add_parser("sync")
    sync_parser.add_argument("target", nargs="?", choices=["project", "area", "resource", "quick", "all"], default="all")

    for bucket in NOTE_BUCKETS:
        note_parser = subparsers.add_parser(bucket)
        note_parser.add_argument("text", nargs="*")
        note_parser.add_argument("--title")
        note_parser.add_argument("--content")
        note_parser.add_argument("--content-file")
        note_parser.add_argument("--folder-hint")
        note_parser.add_argument("--dry-run", action="store_true")

    todo_parser = subparsers.add_parser("todo")
    todo_parser.add_argument("todo_list", choices=list(TODO_FILES))
    todo_parser.add_argument("text", nargs="*")
    todo_parser.add_argument("--content")
    todo_parser.add_argument("--content-file")
    todo_parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> None:
    if not VAULT.exists():
        raise SystemExit(f"Vault not found: {VAULT}")

    parser = build_parser()
    args = parser.parse_args()

    if args.subcmd == "sync":
        run_sync(args.target)
        return

    if args.subcmd == "todo":
        if args.text and not args.content and not args.content_file:
            args.content = " ".join(args.text)
        run_todo(args)
        return

    if args.text and not args.title:
        args.title = " ".join(args.text)
    run_note(args.subcmd, args)


if __name__ == "__main__":
    main()
