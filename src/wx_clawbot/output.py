"""Bounded text rendering; task inputs and native protocol payloads never pass here."""

import asyncio
import json
import re
import sys
import unicodedata
from dataclasses import dataclass

from markdown_it import MarkdownIt


RESULT_LIMIT = 480000
COMPATIBILITY_NOTE = "〔样式兼容：中文斜体与删除线可能显示为普通字形，原文内容和标记已保留。〕\n\n"


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


def _lines(text):
    # Markdown source maps count LF, not U+2028/U+2029 literal data.
    return re.findall(r"[^\n]*\n|[^\n]+$", text)


def _parser():
    return MarkdownIt("commonmark", {"html": False, "maxNesting": 32}).enable(["table", "strikethrough"])


def _inline_prose(value, parser):
    if len(value) > 8192 or any(0xE000 <= ord(char) <= 0xF8FF for char in value):
        return value
    ranges = []
    # The parser reports exact consumed ranges, never reconstructed token text.
    tokens = []
    parser.inline.parse(value, parser, {"literal_ranges": ranges}, tokens)
    pattern = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|(?:https?|ssh|file)://[^\s，。！？；、]+|'
                         r'(?<![\w/])/(?:[^\s，。！？；、`]+)|[A-Za-z0-9_][A-Za-z0-9_./:+%=-]*')
    ranges.extend((m.start(), m.end()) for m in pattern.finditer(value))
    merged = []
    for left, right in sorted(ranges):
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(right, merged[-1][1]))
        else:
            merged.append((left, right))
    pieces, held, position = [], [], 0
    for left, right in merged:
        pieces.extend((value[position:left], chr(0xE000 + len(held))))
        held.append(value[left:right])
        position = right
    pieces.append(value[position:])
    value = "".join(pieces)
    han = r"[\u3400-\u9fff]"
    def spaced(match):
        placeholder = next(char for char in match[0] if 0xE000 <= ord(char) <= 0xF8FF)
        literal = held[ord(placeholder) - 0xE000]
        return " ".join(match.groups()) if not literal.startswith(("\\", "&")) else match[0]
    value = re.sub(f"({han})([\ue000-\uf8ff])", spaced, value)
    value = re.sub(f"([\ue000-\uf8ff])({han})", spaced, value)
    for before, after in ((",", "，"), (";", "；"), (":", "："), ("!", "！"), ("?", "？")):
        value = re.sub(f"(?<={han}){re.escape(before)}|{re.escape(before)}(?={han})", after, value)
    value = re.sub(f"(?<={han})\\.(?!\\.)", "。", value).replace("—", "--")
    return re.sub(r"[\ue000-\uf8ff]", lambda m: held[ord(m[0]) - 0xE000], value)


def _prose_parser():
    parser = _parser()
    rules = zip(parser.inline.ruler.get_active_rules(), parser.inline.ruler.getRules(""))
    literals = {"backticks", "link", "image", "autolink", "escape", "entity"}
    for name, function in list(rules):
        if name not in literals:
            continue
        def capture(state, silent, original=function):
            start = state.pos
            accepted = original(state, silent)
            if accepted and not silent:
                state.env["literal_ranges"].append((start, state.pos))
            return accepted
        parser.inline.ruler.at(name, capture)
    return parser


def format_prose(text):
    """Change only identifiable prose; protect syntax, literals and raw errors."""
    if not re.search(r"[\u3400-\u9fff—]", text):
        return text
    lines = _lines(text)
    parser = _prose_parser()
    protected, processed = set(), set()
    tokens = _parser().parse(text)
    for token in tokens:
        if token.map and token.type in {"fence", "code_block"}:
            protected.update(range(*token.map))
    error = next((i for i, line in enumerate(lines) if line.startswith("原生错误：") and i not in protected), len(lines))
    for token in tokens:
        if token.type != "inline" or not token.map:
            continue
        start, end = token.map
        if any(i in protected or i in processed for i in range(start, end)) or start >= error:
            continue
        raw = "".join(lines[start:end])
        # Shell/code-like prose and reference definitions stay literal.
        if (any(part in raw for part in ("=", "{", "}", "->", "::"))
                or re.search(r"\b[A-Za-z_][A-Za-z0-9_.]*\(", raw)
                or re.match(r"^\s*(?:\$ |>>> |git\b|codex\b|python\d*\b|sh\b|bash\b|zsh\b|echo\b|printf\b|cd\b|pip\b|uv\b|npm\b|node\b|ls\b|rg\b|cat\b|curl\b|import\b|from\b|def\b|class\b|return\b|SELECT\b|INSERT\b|UPDATE\b|DELETE\b)", raw)):
            continue
        replacement = _lines(_inline_prose(raw, parser))
        if len(replacement) == end - start:
            lines[start:end] = replacement
        processed.update(range(start, end))
    return "".join(lines)


def _fence_for(text):
    lengths = {char: max((len(m[0]) for m in re.finditer(re.escape(char) + "+", text)), default=0)
               for char in ("`", "~")}
    # Three backticks are observed on both clients; Mac misrenders tilde fences.
    char = "`" if lengths["`"] < 3 else min(lengths, key=lengths.get)
    return char * max(3, lengths[char] + 1)


def _replace_ranges(text, edits):
    pieces, position = [], 0
    for left, right, replacement in sorted(set(edits)):
        if left < position:
            continue
        pieces.extend((text[position:left], replacement))
        position = right
    pieces.append(text[position:])
    return "".join(pieces)


def _table_fields(raw):
    tokens = _parser().parse(raw)
    if not tokens or tokens[0].type != "table_open":
        return raw
    headers, rows, cells, header_complex = None, [], [], False
    for token in tokens:
        if token.type == "tr_open":
            cells = []
        elif token.type == "inline":
            cells.append(token.content)
            if headers is None and (any(child.type != "text" for child in token.children or [])
                    or re.search(r"[`*~\[\]\\]|(?<!\w)_|_(?!\w)", token.content)
                    or re.match(r"^\s*(?:#|>|[-+*]\s|\d+[.)]\s)", token.content)):
                header_complex = True
        elif token.type == "tr_close":
            if headers is None:
                headers = cells
            else:
                rows.append(cells)
    if headers is None or header_complex:
        return raw
    result = ["表格（字段列表）：\n\n"]
    size = len(result[0])
    if not rows:
        result.append("表头：" + "、".join(headers) + "。\n\n（无数据行）\n\n")
    for index, row in enumerate(rows, 1):
        result.append(f"- 第 {index} 行\n")
        size += len(result[-1])
        for column, header in enumerate(headers):
            name = header or f"第 {column + 1} 列"
            value = row[column] if column < len(row) and row[column] else "（空）"
            field = f"  - {name}：{value}\n"
            size += len(field)
            if size > RESULT_LIMIT:
                fence = _fence_for(raw)
                return ("〔表格字段展开超过展示上限，以下保留表格源文。〕\n\n" + fence + "text\n" + raw
                        + ("" if raw.endswith("\n") else "\n") + fence + "\n\n")
            result.append(field)
    result.append("\n")
    return "".join(result)


def _common_markdown(text):
    """Apply only source-mapped, observed client compatibility transformations."""
    if ("]:" not in text and "~~~" not in text and "|" not in text
            and not re.search(r"[^\n]\n[^\n]", text)):
        return text
    parser = _parser()
    parser.options["store_labels"] = True
    # Preserve target spelling rather than URL-encoding Unicode or percent escapes.
    parser.normalizeLink = lambda value: value
    environment = {}
    tokens = parser.parse(text, environment)
    root_tables = {tuple(token.map) for token in tokens if token.type == "table_open" and token.level == 0 and token.map}
    lines = _lines(text)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    code_lines = {i for token in tokens if token.map and token.type in {"code_block", "fence"}
                  for i in range(*token.map)}
    error = next((i for i, line in enumerate(lines) if line.startswith("原生错误：") and i not in code_lines), len(lines))
    references = {key: ref for key, ref in environment.get("references", {}).items() if ref["map"][0] < error}
    edits, used, growth = [], set(), 0
    overflow = False
    original_link = dict(zip(parser.inline.ruler.get_active_rules(), parser.inline.ruler.getRules("")))["link"]

    def link(state, silent):
        nonlocal growth, overflow
        start, previous = state.pos, len(state.tokens)
        accepted = original_link(state, silent)
        if accepted and not silent:
            state.env["literal_ranges"].append((start, state.pos))
            opening = next((token for token in state.tokens[previous:] if token.type == "link_open"), None)
            label = opening.meta.get("label") if opening else None
            if label in references:
                label_end = state.md.helpers.parseLinkLabel(state, start, True)
                ref = references[label]
                destination = ref["href"]
                if any(char.isspace() for char in destination):
                    destination = "<" + destination + ">"
                title = ref["title"].replace("\\", "\\\\").replace('"', '\\"')
                replacement = "[" + state.src[start + 1:label_end] + "](" + destination + (f' "{title}"' if title else "") + ")"
                growth += max(0, len(replacement) - (state.pos - start))
                if growth > RESULT_LIMIT:
                    overflow = True
                elif not overflow:
                    state.env["link_edits"].append((start, state.pos, replacement))
                used.add(label)
        return accepted

    parser.inline.ruler.at("link", link)
    for rule_name in ("newline", "escape", "backticks", "image", "autolink"):
        original = dict(zip(parser.inline.ruler.get_active_rules(), parser.inline.ruler.getRules("")))[rule_name]
        def capture(state, silent, original=original, name=rule_name):
            start = state.pos
            accepted = original(state, silent)
            if accepted and not silent:
                if name == "newline":
                    state.env["breaks"].append((start, start + 1))
                elif name == "escape" and state.src[start:state.pos] == "\\\n":
                    state.env["breaks"].append((start, start + 2))
                else:
                    state.env["literal_ranges"].append((start, state.pos))
            return accepted
        parser.inline.ruler.at(rule_name, capture)
    spans = {}
    for index, token in enumerate(tokens):
        if not token.map or token.type not in {"inline", "table_open"} or token.map[0] >= error:
            continue
        plain = (token.type == "inline" and token.level == 1 and index > 0
                 and tokens[index - 1].type == "paragraph_open"
                 and not any(child.type in {"em_open", "strong_open", "s_open"} for child in token.children or []))
        spans[(token.map[0], token.map[1], token.type == "table_open")] = plain
    for (start, end, table), plain in sorted(spans.items()):
        raw = "".join(lines[start:end])
        if not references and ((table and (start, end) not in root_tables) or not table and "\n" not in raw.rstrip("\r\n")):
            continue
        env = {"references": references, "literal_ranges": [], "link_edits": [], "breaks": []}
        parser.inline.parse(raw, parser, env, [])
        env["literal_ranges"].extend((match.start(), match.end()) for match in
            re.finditer(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|(?:https?|ssh|file)://[^\s]+|[A-Za-z0-9_][A-Za-z0-9_./:+%=-]*', raw))
        base = offsets[start]
        if table and (start, end) in root_tables:
            edits.append((base, offsets[end], _table_fields(_replace_ranges(raw, env["link_edits"]))))
            continue
        edits.extend((base + left, base + right, value) for left, right, value in env["link_edits"])
        if not plain or table or re.match(r"^\s*(?:\{|[A-Za-z_]\w*\s*=|[A-Za-z_][\w.]*\(|\$ |>>> )", raw):
            continue
        gaps, position = [], 0
        for left, right in sorted(env["literal_ranges"]):
            if left >= position:
                gaps.append(raw[position:left])
            position = max(position, right)
        gaps.append(raw[position:])
        if re.search(r"[*_~`\[\]<>]", "".join(gaps)):
            continue  # Reflowing malformed/cross-line inline markup can change its meaning.
        for left, right in env["breaks"]:
            if right >= len(raw) or any(a <= left < b for a, b in env["literal_ranges"]):
                continue
            beginning = raw.rfind("\n", 0, left) + 1
            quote = re.match(r"^(?: {0,3}> ?)+", raw[beginning:left])
            separator = "\r\n" if left and raw[left - 1] == "\r" else "\n"
            edits.append((base + left, base + right, "\n" + (quote[0] if quote else "") + separator))
    if overflow:
        fence = _fence_for(text)
        return ("〔引用链接展开超过展示上限，以下保留源文；完整内容见原终端。〕\n\n" + fence + "text\n" + text
                + ("" if text.endswith("\n") else "\n") + fence + "\n")
    definitions = [{**ref, "label": label} for label, ref in references.items()]
    definitions += [ref for ref in environment.get("duplicate_refs", []) if ref["map"][0] < error]
    for definition in definitions:
        start, end = definition["map"]
        raw = "".join(lines[start:end])
        if definition["label"] in used and definition["map"] == references[definition["label"]]["map"]:
            replacement = ""
        else:
            fence = _fence_for(raw)
            replacement = "链接定义（原文）：\n\n" + fence + "text\n" + raw + ("" if raw.endswith("\n") else "\n") + fence + "\n\n"
        edits.append((offsets[start], offsets[end], replacement))
    for token in tokens:
        if token.type != "fence" or not token.map or token.map[0] >= error or not token.markup.startswith("~"):
            continue
        if "```" in token.content or "`" in token.info:
            continue  # Cannot safely use the shared three-backtick representation.
        start, end = token.map
        opening = lines[start].replace(token.markup, "```", 1)
        edits.append((offsets[start], offsets[start + 1], opening))
        closing = re.fullmatch(r"([ >\t]*)(~{3,})([ \t]*(?:\r?\n)?)", lines[end - 1])
        if end - start > 1 and closing and len(closing[2]) >= len(token.markup):
            edits.append((offsets[end - 1], offsets[end], closing[1] + "```" + closing[3]))
    return bounded(_replace_ranges(text, edits), RESULT_LIMIT)


def _parenthetical_links(text):
    """Keep exact complex HTTPS targets outside the client's broken ](...) form."""
    if "]" not in text:
        return text
    parser = _parser()
    parser.normalizeLink = lambda value: value
    tokens = parser.parse(text)
    lines = _lines(text)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    code_lines = {i for token in tokens if token.map and token.type in {"fence", "code_block"}
                  for i in range(*token.map)}
    error = next((i for i, line in enumerate(lines) if line.startswith("原生错误：") and i not in code_lines), len(lines))
    contexts = {}
    for index, token in enumerate(tokens):
        if token.type != "inline" or not token.map:
            continue
        standalone = (index > 0 and tokens[index - 1].type == "paragraph_open"
                      and not any(t.type in {"em_open", "strong_open", "s_open"} for t in token.children or []))
        contexts.update((i, standalone) for i in range(*token.map) if i < error)
    original = dict(zip(parser.inline.ruler.get_active_rules(), parser.inline.ruler.getRules("")))["link"]

    def link(state, silent):
        start, previous = state.pos, len(state.tokens)
        accepted = original(state, silent)
        if not accepted or silent or state.env.get("image"):
            return accepted
        opening = next((t for t in state.tokens[previous:] if t.type == "link_open"), None)
        href = opening.attrGet("href") if opening else None
        if (not href or not href.startswith("https://") or not any(c in href for c in "()") or any(c in href for c in "<>")
                or any(c.isspace() for c in href) or any(a <= start < b for a, b in state.env["quoted"])):
            return accepted
        end = state.md.helpers.parseLinkLabel(state, start, True)
        if end < 0:
            return accepted
        prefix = state.env["prefix"]
        standalone = state.env["standalone"]
        separator = "\n" + prefix.rstrip() + "\n" + prefix if standalone else "，"
        label = state.src[start + 1:end]
        replacement = label + separator + "<" + href + ">" if standalone else label + "（<" + href + ">"
        title = opening.attrGet("title")
        if title:
            fence = "`" * (max((len(m[0]) for m in re.finditer(r"`+", title)), default=0) + 1)
            pad = " " if title.startswith("`") or title.endswith("`") or (title.startswith(" ") and title.endswith(" ") and title.strip(" ")) else ""
            replacement += separator + "链接标题：" + fence + pad + title + pad + fence
        if not standalone:
            replacement += "）"
        elif state.src[state.pos:].strip():
            replacement += separator
        state.env["edits"].append((start, state.pos, replacement))
        return accepted

    parser.inline.ruler.at("link", link)
    original_image = dict(zip(parser.inline.ruler.get_active_rules(), parser.inline.ruler.getRules("")))["image"]

    def image(state, silent):
        previous = state.env.get("image", False)
        state.env["image"] = True
        try:
            return original_image(state, silent)
        finally:
            state.env["image"] = previous

    parser.inline.ruler.at("image", image)
    edits = []
    for index in sorted(contexts):
        raw = lines[index]
        if "]" not in raw:
            continue
        marker = re.match(r"^((?: {0,3}> ?)*)([ \t]*)(?:(?:[-+*]|\d+[.)])([ \t]+))?", raw)
        prefix = marker[1] + marker[2]
        if marker[3] is not None:
            prefix += " " * (marker.end() - len(prefix))
        env = {"prefix": prefix, "standalone": contexts[index], "edits": [], "quoted": [m.span() for m in
               re.finditer(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', raw)]}
        parser.inline.parse(raw, parser, env, [])
        edits.extend((offsets[index] + a, offsets[index] + b, value) for a, b, value in env["edits"])
    return bounded(_replace_ranges(text, edits), RESULT_LIMIT)


def _list_code_compatibility(text):
    """Detach simple item continuations/code with observed explicit ownership labels."""
    if not re.search(r"(?m)^ +(?:`{3,}|~{3,})", text):
        return text
    tokens = _parser().parse(text)
    lines = _lines(text)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    code_lines = {i for t in tokens if t.map and t.type in {"fence", "code_block"} for i in range(*t.map)}
    error = next((i for i, line in enumerate(lines) if line.startswith("原生错误：") and i not in code_lines), len(lines))
    edits, item, number = [], None, 0
    for index, token in enumerate(tokens):
        if token.level == 0 and token.type in {"bullet_list_open", "ordered_list_open"}:
            number = int(token.attrGet("start") or 1) - 1
        elif token.type == "list_item_open" and token.level == 1:
            number += 1
            item = index
        elif token.type == "list_item_close" and token.level == 1 and item is not None:
            children = tokens[item + 1:index]
            item = None
            # Only the observed flat item's paragraphs and fences are promoted.
            # Nested lists/quotes and unknown blocks retain their source structure.
            if (not any(t.type == "fence" and t.level == 2 for t in children)
                    or any(t.map and t.type not in {"paragraph_open", "inline", "fence"} for t in children)):
                continue
            paragraphs = [t for t in children if t.type == "paragraph_open"]
            if not paragraphs:
                continue
            header = lines[paragraphs[0].map[0]]
            marker = re.match(r"^ {0,3}(?:[-+*]|\d+[.)])([ ]+)", header)
            if not marker:
                continue
            prefix = " " * marker.end()
            pending = []
            for child in children:
                if child.type not in {"paragraph_open", "fence"} or child is paragraphs[0]:
                    continue
                start, end = child.map
                if start >= error:
                    pending = []
                    break
                source = lines[start:end]
                if child.type == "paragraph_open":
                    if any(line.strip() and not line.startswith(prefix) for line in source):
                        pending = []
                        break
                    body = "".join(line[len(prefix):] if line.startswith(prefix) else line for line in source)
                    label = "续段"
                else:
                    opening = re.match(r"^( *)(`{3,}|~{3,})([^\r\n]*)(\r?\n)$", source[0])
                    if not opening or len(source) < 2:
                        pending = []
                        break
                    indent, fence = opening[1], opening[2]
                    closing = re.fullmatch(r" *" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}[ \t]*(?:\r?\n)?", source[-1])
                    if not closing or any(line.strip() and not line.startswith(indent) for line in source):
                        pending = []
                        break
                    body = "".join(line[len(indent):] if line.startswith(indent) else line for line in source)
                    label = "代码"
                replacement = f"\n\n**第 {number} 项{label}：**\n\n" + body
                replacement += "\n\n" if not replacement.endswith("\n") else "\n"
                pending.append((offsets[start], offsets[end], replacement))
            edits.extend(pending)
    return _replace_ranges(text, edits)


def display_text(text):
    """Android-compatible Markdown; no task inputs or historical outbox here."""
    if not isinstance(text, str) or not text or len(text) > 512000:
        raise ValueError("Bounded nonempty display source required")
    if re.search(r"\r(?!\n)", text):
        return text  # Preserve literal bare CR; segmentation will label fragments.
    text = format_prose(_parenthetical_links(_common_markdown(text)))
    lines = _lines(text)
    changes = []
    tokens = _parser().parse(text)
    code_lines = {i for token in tokens if token.map and token.type in {"fence", "code_block"} for i in range(*token.map)}
    error = next((i for i, line in enumerate(lines) if line.startswith("原生错误：") and i not in code_lines), len(lines))
    compatibility_note = False
    for token in tokens:
        if not token.map:
            continue
        start, end = token.map
        if start >= error:
            continue
        if token.type == "inline" and token.children:
            emphasis = 0
            for child in token.children:
                emphasis += int(child.type == "em_open") - int(child.type == "em_close")
                if child.type == "s_open" or emphasis > 0 and re.search(r"[\u3400-\u9fff]", child.content):
                    compatibility_note = True
        raw = "".join(lines[start:end])
        if token.type == "heading_open":
            level = int(token.tag[1])
            label = "一二三四五六"[level - 1]
            if token.markup.startswith("#"):
                match = re.match(r"^(.*?)(#{1,6})(?:[ \t]+|$)(.*?)(\r?\n)?$", lines[start])
                if not match:
                    continue
                body = re.sub(r"[ \t]+#+[ \t]*$", "", match[3])
                replacement = match[1] + f"**【{label}级标题】** " + body + (match[4] or "")
            else:
                # Setext: only remove its syntax line, retaining title lines.
                prefix = re.match(r"^(?: {0,3}> ?)*(?: {0,3}(?:[-+*]|\d+[.)])[ \t]+)?[ \t]*", lines[start])[0]
                replacement = prefix + f"**【{label}级标题】** " + lines[start][len(prefix):] + "".join(lines[start + 1:end - 1])
            # Preserve the heading's block boundary after converting it into a
            # compatibility paragraph; inline emphasis cannot leak to the next block.
            if end < len(lines) and lines[end].strip():
                quote = re.match(r"^(?: {0,3}> ?)+", lines[start])
                replacement += ("" if replacement.endswith("\n") else "\n") + (quote[0] if quote else "") + "\n"
            changes.append((start, end, replacement))
        elif token.type == "code_block":
            # Keep source indentation, including the four structural spaces.
            # Containers need their source prefix on the newly inserted fences.
            first = lines[start]
            quote = re.match(r"^(?: {0,3}> ?)+", first)
            prefix = quote[0] if quote else " " * (max(0, len(first) - len(first.lstrip(" ")) - 4) if token.level else 0)
            fence = _fence_for(raw)
            # A list consumes its continuation prefix from fenced body lines.
            # Repeat that structural prefix so the copied content keeps every
            # original source space rather than losing it to list indentation.
            body = raw if quote else "".join(prefix + line for line in _lines(raw))
            replacement = prefix + fence + "text\n" + body
            replacement += ("" if raw.endswith("\n") else "\n") + prefix + fence + "\n"
            changes.append((start, end, replacement))
    for start, end, replacement in sorted(changes, reverse=True):
        lines[start:end] = [replacement]
    result = "".join(lines)
    if compatibility_note and not result.startswith(COMPATIBILITY_NOTE):
        result = COMPATIBILITY_NOTE + result
    return bounded(_list_code_compatibility(result), RESULT_LIMIT)


@dataclass(frozen=True)
class DisplaySegment:
    """Exact source slice plus recorded display-only repairs, never persisted as metadata."""
    source: str
    before: str = ""
    after: str = ""

    @property
    def text(self):
        return self.before + self.source + self.after


def _safe_end(text, start, end):
    candidate = end
    while candidate > start and candidate < len(text) and (
            unicodedata.combining(text[candidate]) or text[candidate] in "\ufe0e\ufe0f\u200d"
            or text[candidate - 1] == "\u200d" or 0x1F3FB <= ord(text[candidate]) <= 0x1F3FF
            or text[candidate - 1:candidate + 1] == "\r\n"):
        candidate -= 1
    return candidate if candidate > start else end


def _fragments(raw, budget, reason="此结构过长或边界未闭合"):
    result, start = [], 0
    while start < len(raw):
        end = _safe_end(raw, start, min(start + budget // 3, len(raw)))
        part = raw[start:end]
        fence = _fence_for(part)
        before = f"〔原文片段：{reason}，不能作为单个完整链接／代码块复制；完整内容见原终端。〕\n\n" + fence + "text\n"
        after = ("" if part.endswith("\n") else "\n") + fence + "\n"
        result.append(DisplaySegment(part, before, after))
        start = end
    return result


def _code_segments(raw, budget):
    lines = _lines(raw)
    opening = lines[0]
    marker = re.match(r"^ {0,3}(`{3,}|~{3,})", opening)
    if not marker or len(opening) > 300:
        return _fragments(raw, budget)
    fence = marker[1]
    closed = len(lines) > 1 and re.fullmatch(r" {0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}[ \t]*(?:\r?\n)?", lines[-1])
    if not closed or any(len(line) > budget - len(opening) - len(fence) - 8 for line in lines):
        return _fragments(raw, budget)
    result, current = [], ""
    for line in lines:
        before = opening if result else ""
        if current and len(before + current + line) + len(fence) + 2 > budget:
            after = ("" if current.endswith("\n") else "\n") + fence + "\n"
            result.append(DisplaySegment(current, before, after))
            current = ""
        current += line
    if current:
        result.append(DisplaySegment(current, opening if result else ""))
    return result


def render_segments(text, *, prefix=None):
    """Render once, split at parser boundaries, account for every repair/prefix."""
    text = display_text(text)
    if re.search(r"\r(?!\n)", text):
        parts = _fragments(text, 6400)
        result = []
        for index, part in enumerate(parts, 1):
            heading = prefix(index, len(parts)) if prefix else ""
            if not isinstance(heading, str) or len(heading) > 384:
                raise ValueError("Bounded display prefix required")
            result.append(DisplaySegment(part.source, heading + part.before, part.after))
        return result
    env = {}
    tokens = _parser().parse(text, env)
    lines = _lines(text)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    cuts = {0, len(text)}
    fences = {}
    isolated = set()
    nested_code = iter(sorted({t.map[0] for t in tokens if t.map and t.level > 0
                              and t.type in {"fence", "code_block"}}))
    code_start = next(nested_code, None)
    for token in tokens:
        if not token.map or token.level or token.type not in {"bullet_list_open", "ordered_list_open", "blockquote_open"}:
            continue
        start, end = token.map
        while code_start is not None and code_start < start:
            code_start = next(nested_code, None)
        if code_start is not None and code_start < end:
            isolated.update((offsets[start], offsets[end]))
    for token in tokens:
        if token.map and token.level == 0 and token.type != "inline":
            left, right = (offsets[i] for i in token.map)
            cuts.update((left, right))
            if token.type == "fence":
                fences[(left, right)] = True
        elif token.map and token.type == "list_item_open" and token.level == 1:
            cuts.update(offsets[i] for i in token.map)
    explicit_list_code = any(t.type == "inline" and t.level == 1
                             and re.fullmatch(r"\*\*第 \d+ 项代码：\*\*", t.content) for t in tokens)
    if isolated or explicit_list_code:
        for left, right in fences:
            isolated.update((left, right))
        cuts.update(isolated)
    definitions = "".join("".join(lines[ref["map"][0]:ref["map"][1]]) for ref in env.get("references", {}).values())
    # Reference definitions may be elsewhere in the result; repeat exact source as
    # display-only suffixes so every independently rendered message can resolve it.
    suffix = "\n\n" + definitions if definitions and len(text) > 6000 else ""
    budget = 6800 - min(len(suffix), 6800)
    if budget < 2000 or len(isolated) > 64:
        result = _fragments(text, 6400, "复杂代码容器过多" if len(isolated) > 64 else "此结构过长或边界未闭合")
        suffix = ""
    else:
        result, pending = [], ""
        points = sorted(cuts)
        for left, right in zip(points, points[1:]):
            unit = text[left:right]
            if left in isolated and pending:
                result.append(DisplaySegment(pending))
                pending = ""
            if len(unit) <= budget:
                if pending and len(pending) + len(unit) > budget:
                    result.append(DisplaySegment(pending))
                    pending = ""
                pending += unit
                continue
            if pending:
                result.append(DisplaySegment(pending))
                pending = ""
            if (left, right) in fences:
                result.extend(_code_segments(unit, budget))
            elif not re.search(r"[\\`*_\[\]<>~|]|(?:https?|ssh|file)://|^[ \t]*(?:[-+*]|\d+[.)])[ \t]+|[A-Za-z0-9_/.-]{6801,}", unit):
                start = 0
                while start < len(unit):
                    end = _safe_end(unit, start, min(start + budget, len(unit)))
                    result.append(DisplaySegment(unit[start:end]))
                    start = end
            else:
                result.extend(_fragments(unit, budget))
        if pending:
            result.append(DisplaySegment(pending))
    # Blank source gaps belong to an adjacent payload, never an empty outbox
    # row. Repairs remain recorded separately for exact reconstruction.
    combined = []
    for part in result:
        if not part.source.strip() and not part.before and not part.after:
            if combined and len(combined[-1].text) + len(part.source) <= budget:
                previous = combined.pop()
                combined.append(DisplaySegment(previous.source + part.source, previous.before, previous.after))
            else:
                combined.extend(_fragments(part.source, max(2000, budget)))
        else:
            combined.append(part)
    result = combined
    final = []
    for index, part in enumerate(result, 1):
        heading = prefix(index, len(result)) if prefix else ""
        if not isinstance(heading, str) or len(heading) > 384:
            raise ValueError("Bounded display prefix required")
        segment = DisplaySegment(part.source, heading + part.before, part.after + suffix)
        if len(segment.text) > 8000:
            raise ValueError("Display payload exceeds local transport bound")
        final.append(segment)
    return final


def display_segments(text, *, prefix=None):
    return [segment.text for segment in render_segments(text, prefix=prefix)]


async def _render_process(text):
    """One killable CPU worker; the protocol contains display data, never code."""
    limit = 8 * 1024 * 1024
    payload = json.dumps({"text": text}, ensure_ascii=False).encode()
    if len(payload) > limit:
        raise ValueError("Display worker input exceeds bound")
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-I", "-m", "wx_clawbot.render_worker",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    async def write_input():
        process.stdin.write(payload)
        await process.stdin.drain()
        process.stdin.close()
        await process.stdin.wait_closed()
    async def read_output():
        chunks, size = [], 0
        while chunk := await process.stdout.read(65536):
            size += len(chunk)
            if size > limit:
                raise ValueError("Display worker output exceeds bound")
            chunks.append(chunk)
        return b"".join(chunks)
    io = []
    try:
        async with asyncio.timeout(20):
            io = [asyncio.create_task(write_input()), asyncio.create_task(read_output())]
            _, raw = await asyncio.gather(*io)
            if len(raw) > limit:
                raise ValueError("Display worker output exceeds bound")
            if await process.wait() != 0:
                raise ValueError("Display worker failed")
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) != {"parts", "peak_rss_bytes"}:
            raise ValueError("Invalid display worker envelope")
        parts = value["parts"]
        if not isinstance(parts, list) or not 1 <= len(parts) <= 2048:
            raise ValueError("Invalid display worker segment count")
        result = []
        for item in parts:
            if (not isinstance(item, dict) or set(item) != {"source", "before", "after"}
                    or any(not isinstance(item[key], str) for key in item)):
                raise ValueError("Invalid display worker segment")
            part = DisplaySegment(**item)
            if not part.text.strip() or len(part.text) > 8000:
                raise ValueError("Invalid bounded display worker payload")
            result.append(part)
        if type(value["peak_rss_bytes"]) is not int or value["peak_rss_bytes"] <= 0:
            raise ValueError("Invalid display worker memory metric")
        return result, value["peak_rss_bytes"]
    finally:
        for job in io:
            if not job.done():
                job.cancel()
        await asyncio.gather(*io, return_exceptions=True)
        if process.returncode is None:
            process.kill()
            await process.wait()


async def render_in_worker(text, *, renderer=None, slots=None, **kwargs):
    """A cancelled owner retains its CPU lane until the actual renderer exits."""
    if not isinstance(text, str) or not text or len(text) > 512000:
        raise ValueError("Bounded nonempty display source required")
    if len(text) >= 65536 and (renderer is None or renderer is render_segments):
        prefix = kwargs.pop("prefix", None)
        if kwargs:
            raise ValueError("Unsupported display worker options")
        async with (slots if slots is not None else asyncio.Semaphore(2)):
            parts, _ = await _render_process(text)
        result = []
        for index, part in enumerate(parts, 1):
            heading = prefix(index, len(parts)) if prefix else ""
            if not isinstance(heading, str) or len(heading) > 384:
                raise ValueError("Bounded display prefix required")
            segment = DisplaySegment(part.source, heading + part.before, part.after)
            if len(segment.text) > 8000:
                raise ValueError("Display payload exceeds local transport bound")
            result.append(segment)
        return result
    job = asyncio.create_task(asyncio.to_thread(renderer or render_segments, text, **kwargs))
    try:
        return await asyncio.shield(job)
    except asyncio.CancelledError:
        await job
        raise


def native_output(turn):
    body = "\n".join(item.get("text", "") for item in turn.get("items", [])
                     if item.get("type") == "agentMessage" and item.get("phase") != "commentary"
                     and isinstance(item.get("text"), str))
    body = bounded(body, RESULT_LIMIT)
    error = turn.get("error")
    if turn.get("status") == "failed" and isinstance(error, dict) and isinstance(error.get("message"), str) and error["message"].strip():
        body = (body + "\n\n原生错误：" + bounded(error["message"], 8000)).strip()
    return body or "原生任务已结束，没有最终文本结果。"
