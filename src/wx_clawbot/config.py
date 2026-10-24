"""Strict, read-only configuration loading; never imports another project's data."""

import json
from dataclasses import dataclass
from pathlib import Path


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Project:
    alias: str
    root: Path


def load_projects(path: Path) -> tuple[Project, ...]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigError("配置不可读或 JSON 格式无效。") from exc
    if not isinstance(value, dict) or set(value) != {"projects"}:
        raise ConfigError("配置只接受 projects 字段。")
    if not isinstance(value["projects"], list) or not value["projects"]:
        raise ConfigError("projects 必须是非空列表。")
    projects = []
    aliases, roots = set(), set()
    for item in value["projects"]:
        if not isinstance(item, dict) or set(item) != {"alias", "root"}:
            raise ConfigError("项目只接受 alias、root 字段。")
        alias, raw = item["alias"], item["root"]
        if not isinstance(alias, str) or not alias or not alias.isascii() or any(
            not (c.isalnum() or c in "-_") for c in alias
        ):
            raise ConfigError("项目别名必须使用英文字母、数字、连字符或下划线。")
        if not isinstance(raw, str) or not Path(raw).expanduser().is_absolute():
            raise ConfigError("项目根目录必须是绝对路径。")
        try:
            root = Path(raw).expanduser().resolve(strict=True)
        except (OSError, ValueError) as exc:
            raise ConfigError("项目根目录不可访问。") from exc
        if not root.is_dir():
            raise ConfigError("项目根目录必须是目录。")
        if alias in aliases or root in roots:
            raise ConfigError("项目别名和真实根目录不得重复。")
        aliases.add(alias)
        roots.add(root)
        projects.append(Project(alias, root))
    return tuple(projects)


def resolve_directory(project: Project, value: str) -> Path:
    if not value.strip():
        raise ConfigError("目录不能为空。")
    candidate = Path(value).expanduser()
    try:
        resolved = (candidate if candidate.is_absolute() else project.root / candidate).resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise ConfigError("目录不可访问。") from exc
    if not resolved.is_dir() or not resolved.is_relative_to(project.root):
        raise ConfigError("目录不在已注册项目范围内。")
    return resolved
