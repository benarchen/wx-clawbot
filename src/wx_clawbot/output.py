"""Bounded text rendering; task inputs and native protocol payloads never pass here."""

import re


RESULT_LIMIT = 480000


def split_text(text, limit=7000):
    if not isinstance(text, str) or not text or type(limit) is not int or not 100 <= limit <= 7000:
        raise ValueError("Text and a bounded transport segment size required")
    chunks, start = [], 0
    while start < len(text):
        end = min(start + limit, len(text))
        if end < len(text):
            newline = text.rfind("\n", start + limit // 2, end)
            if newline >= 0:
                end = newline + 1
        chunks.append(text[start:end])
        start = end
    return chunks


def bounded(text, limit):
    if len(text) <= limit:
        return text
    notice = "\n\n〔内容超过微信回执上限，保留开头与末尾；完整内容请在原终端查看。〕\n\n"
    available = limit - len(notice)
    return text[:available // 2] + notice + text[-(available - available // 2):]


def format_prose(text):
    """Normalize identifiable prose while keeping code, quoted strings and tokens literal."""
    lines, fence = [], None
    protected = re.compile(r"```[^`\n]*```|``[^`\n]*``|`[^`\n]*`|\"[^\"\n]*\"|'[^'\n]*'|(?:https?|ssh|file)://[^\s，。！？；、]+|"
                           r"(?<![\w/])/(?:[^\s，。！？；、`]+)|[A-Za-z0-9_][A-Za-z0-9_./:+%=-]*")
    han = r"[\u3400-\u9fff]"
    for line in text.splitlines(keepends=True):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if marker:
            if fence is None:
                fence = marker[1][0]
            elif marker[1][0] == fence:
                fence = None
            lines.append(line)
            continue
        if fence or len(line) > 8192 or line.startswith(("    ", "\t", "$ ", ">>> ")) or any(token in line for token in ("=", "{", "}", "->", "::")):
            lines.append(line)
            continue
        code_like = ("(" in line and re.search(r"\b[A-Za-z_][A-Za-z0-9_.]*\(", line)) or re.match(
            r"^\s*(?:git|codex|python\d*|sh|bash|zsh|echo|printf|cd|pip|uv|npm|node|ls|rg|cat|curl|import|from|def|class|return|SELECT|INSERT|UPDATE|DELETE)\b", line)
        if code_like:
            lines.append(line)
            continue
        tokens = []
        def hold(match):
            tokens.append(match[0])
            return chr(0xE000 + len(tokens) - 1)
        # Private-use characters in original text must not collide with placeholders.
        if any(0xE000 <= ord(char) <= 0xF8FF for char in line):
            lines.append(line)
            continue
        value = protected.sub(hold, line)
        value = re.sub(f"({han})([\ue000-\uf8ff])", r"\1 \2", value)
        value = re.sub(f"([\ue000-\uf8ff])({han})", r"\1 \2", value)
        for before, after in ((",", "，"), (";", "；"), (":", "："), ("!", "！"), ("?", "？")):
            value = re.sub(f"(?<={han}){re.escape(before)}|{re.escape(before)}(?={han})", after, value)
        value = re.sub(f"(?<={han})\\.(?!\\.)", "。", value).replace("—", "--")
        for index, token in enumerate(tokens):
            value = value.replace(chr(0xE000 + index), token)
        lines.append(value)
    return "".join(lines)


def native_output(turn):
    body = "\n".join(item.get("text", "") for item in turn.get("items", [])
                     if item.get("type") == "agentMessage" and isinstance(item.get("text"), str))
    body = bounded(format_prose(bounded(body, RESULT_LIMIT)), RESULT_LIMIT)
    error = turn.get("error")
    if turn.get("status") == "failed" and isinstance(error, dict) and isinstance(error.get("message"), str) and error["message"].strip():
        body = (body + "\n\n原生错误：" + bounded(error["message"], 8000)).strip()
    return body or "原生任务已结束，没有文本结果。"
