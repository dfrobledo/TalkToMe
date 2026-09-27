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


def lead(markdown, keep_tags=False):
    """First speakable prose paragraph: the 'spoken summary' of a reply."""
    without_code = FENCE.sub("\n\n", markdown or "")
    for block in re.split(r"\n\s*\n", without_code):
        first = block.strip().splitlines()[0].strip() if block.strip() else ""
        if not first or first.startswith(("#", "|", ">")) or LIST_MARKER.match(first):
            continue
        spoken = to_speech(block, keep_tags=keep_tags)
        if re.search(r"\w", spoken):
            return spoken
    return ""


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
