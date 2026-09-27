"""Turn Claude's markdown into text that sounds natural when spoken.

TTS engines read literally: asterisks, backticks, paths and code blocks
ruin the illusion. This module strips what should not be heard and adds
the punctuation that gives the voice its pauses.
"""
import re

FENCE = re.compile(r"```.*?(?:```|\Z)", re.S)
IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
URL = re.compile(r"https?://\S+")
INLINE_CODE = re.compile(r"`([^`\n]+)`")
HTML_TAG = re.compile(r"</?[A-Za-z][^>]*>")
AUDIO_TAG = re.compile(r"\[[A-Za-z][A-Za-z \-]{0,30}\]")
EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍]+"
)
LIST_MARKER = re.compile(r"^(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?")
RULE = re.compile(r"^[-*_=]{3,}$")
SENTENCE_END = re.compile(r"[.!?…:;,]$")


def _speak_code(match):
    code = match.group(1).strip()
    if "/" in code or "\\" in code:
        # A path is noise when spoken; the file name carries the meaning.
        code = re.split(r"[/\\]", code.rstrip("/\\"))[-1] or code
    return code.replace("_", " ")


def _inline(text, keep_tags):
    text = IMAGE.sub("", text)
    text = LINK.sub(r"\1", text)
    text = URL.sub("el enlace en pantalla", text)
    text = INLINE_CODE.sub(_speak_code, text)
    text = HTML_TAG.sub("", text)
    if not keep_tags:
        text = AUDIO_TAG.sub("", text)
    text = EMOJI.sub("", text)
    text = text.replace("**", "").replace("__", "").replace("~~", "")
    text = re.sub(r"(?<!\w)\*(?!\s)|(?<!\s)\*(?!\w)", "", text)
    text = text.replace("→", ", ").replace("->", ", ").replace("=>", ", ")
    return re.sub(r"\s+", " ", text).strip()


def to_speech(markdown, code_phrase="Le dejé el código en pantalla.", keep_tags=False):
    """Convert a full markdown response into speakable paragraphs."""
    text = FENCE.sub(f"\n\n{code_phrase}\n\n", markdown or "")
    paragraphs, current = [], []

    def flush():
        if current:
            paragraphs.append(" ".join(current))
            current.clear()

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("|") or RULE.match(line):
            flush()
            continue
        is_block = line.startswith("#") or bool(LIST_MARKER.match(line))
        line = re.sub(r"^#{1,6}\s*", "", line)
        line = re.sub(r"^>\s?", "", line)
        line = LIST_MARKER.sub("", line)
        line = _inline(line, keep_tags)
        if not line:
            continue
        if is_block:
            # Headings and bullets need a full stop or they run together.
            flush()
            if not SENTENCE_END.search(line):
                line += "."
            paragraphs.append(line)
        else:
            current.append(line)
    flush()

    # Collapse repeated code placeholders ("código... código...").
    out = []
    for p in paragraphs:
        if not (out and p == out[-1] == code_phrase):
            out.append(p)
    return "\n\n".join(out).strip()


def spoken_summary(markdown, keep_tags=False):
    """The reply's opening paragraph, only if it really is a spoken summary.

    A summary is the very first block and pure prose: no headings, lists,
    tables, code or a colon that introduces a list. Anything else means the
    reply did not follow the Rachel style (e.g. a project's own format won).
    """
    blocks = [b.strip() for b in re.split(r"\n\s*\n", (markdown or "").strip()) if b.strip()]
    if not blocks:
        return ""
    first = blocks[0]
    lines = [line.strip() for line in first.splitlines()]
    if "`" in first or any(
        line.startswith(("#", "|", ">")) or LIST_MARKER.match(line) for line in lines
    ):
        return ""
    if first.rstrip().endswith(":") or not re.search(r"[.!?…]", first):
        return ""
    spoken = to_speech(first, keep_tags=keep_tags)
    return spoken if len(spoken) >= 15 else ""


ASKS = re.compile(
    r"(\?|qu[eé] necesito de (ti|usted)|necesito (que|su|una|saber)|pregunta\s*:|¿"
    r"|decid(e|a|ir)|confirm(a|e|ar)|av[ií]s(ame|eme)|d[ií](me|game)\b|conect(a|e) )",
    re.I,
)


def asks(text):
    """Does this (short) text ask the user for something anywhere?"""
    return bool(ASKS.search(FENCE.sub("", text or "")))


def needs_input(markdown):
    """Does the reply end by asking the user for something?"""
    tail = FENCE.sub("", markdown or "").strip()[-700:]
    return bool(ASKS.search(tail))


def truncate(text, max_chars):
    """Cut at a sentence boundary so the voice never stops mid-word."""
    if len(text) <= max_chars:
        return text, False
    cut = text[:max_chars]
    ends = [m.end() for m in re.finditer(r"[.!?…](?=\s|$)", cut)]
    if ends and ends[-1] > max_chars * 0.4:
        cut = cut[: ends[-1]]
    else:
        cut = cut.rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return cut.strip(), True
