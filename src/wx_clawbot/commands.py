"""Fixed WeChat command grammar; ordinary text is never evaluated as shell."""

import re
from dataclasses import dataclass


class CommandError(ValueError):
    pass


ALIASES = {"ss": "sessions", "s": "send", "f": "focus", "uf": "unfocus",
           "a": "attach", "ua": "detach"}
NO_ARGUMENTS = {"projects", "unfocus", "detach", "help"}
OPTIONAL_TEXT = {"sessions", "new"}
OPTIONAL_ID = {"status", "stop"}
REQUEST_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")


@dataclass(frozen=True)
class Command:
    name: str
    argument: str = ""
    index: int | None = None
    text: str = ""


def parse_command(value: str) -> Command:
    if not isinstance(value, str) or not value.strip() or len(value) > 32000 or "\0" in value:
        raise CommandError("消息须为非空文本，且不超过 32000 个字符。")
    stripped = value.lstrip()
    if not stripped.startswith("/"):
        return Command("message", text=value)
    match = re.fullmatch(r"/([A-Za-z]+)(?:[ \t]+([\s\S]*))?", stripped)
    if match is None:
        raise CommandError("命令格式无效，请使用 /help。")
    name = ALIASES.get(match[1], match[1])
    argument = match[2] or ""
    if name in NO_ARGUMENTS:
        if argument.strip():
            raise CommandError("该命令不接受参数。")
        return Command(name)
    if name in OPTIONAL_TEXT or name == "cd":
        argument = argument.strip()
        if name == "cd" and not argument:
            raise CommandError("请指定项目别名或目录。")
        if len(argument) > (128 if name == "new" else 4096):
            raise CommandError("命令参数过长。")
        return Command(name, argument=argument)
    if name in OPTIONAL_ID or name in {"approve", "deny"}:
        argument = argument.strip()
        if (not argument and name not in OPTIONAL_ID) or (argument and not REQUEST_ID.fullmatch(argument)):
            raise CommandError("请提供准确的请求或任务 ID。")
        return Command(name, argument=argument)
    if name in {"focus", "attach", "send"}:
        target = re.fullmatch(r"([1-9][0-9]{0,5})(?:[ \t\r\n]([\s\S]*))?",
                              argument if name == "send" else argument.strip())
        if target is None:
            raise CommandError("请使用当前列表中的正整数序号。")
        text = target[2] or ""
        if name == "send" and not text.strip():
            raise CommandError("请在会话序号后提供指令。")
        if name != "send" and text.strip():
            raise CommandError("该命令只接受一个会话序号。")
        return Command(name, index=int(target[1]), text=text)
    if name == "answer":
        request = re.fullmatch(r"([^ \t]+)[ \t]+([\s\S]+)", argument.strip())
        if request is None or not REQUEST_ID.fullmatch(request[1]) or not request[2].strip():
            raise CommandError("请提供请求 ID 和回答。")
        return Command(name, argument=request[1], text=request[2])
    raise CommandError("未知命令，请使用 /help。")
