"""Read Claude Code's session transcript (JSONL) to find the final reply."""
import json


def _blocks(entry):
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [b for b in content or [] if isinstance(b, dict)]


def final_reply(path):
    """Text of the last assistant message after its last tool call.

    Intermediate narration ("let me check the file...") is skipped: only
    the closing answer of the turn is worth saying out loud.
    """
    try:
        with open(path, encoding="utf-8") as f:
            entries = [json.loads(line) for line in f if line.strip()]
    except (OSError, ValueError):
        return ""

    parts = []
    for entry in reversed(entries):
        if entry.get("isSidechain"):
            continue
        kind = entry.get("type")
        if kind == "user":
            # A tool result or a real prompt both mark the start of the reply.
            break
        if kind != "assistant":
            continue
        stop = False
        for block in reversed(_blocks(entry)):
            if block.get("type") == "tool_use":
                stop = True
                break
            if block.get("type") == "text" and block.get("text", "").strip():
                parts.append(block["text"])
        if stop:
            break
    return "\n\n".join(reversed(parts)).strip()
