"""Strict, read-only configuration loading; never imports another project's data."""

import json
import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Project:
    alias: str
    root: Path


@dataclass(frozen=True)
class ProjectConfig:
    projects: tuple[Project, ...]
    workspace_root: Path | None = None
    revision: int = 0
    operations: tuple[dict, ...] = ()
    digest: str = "missing"


def valid_alias(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]+", value) is not None


def forbidden(path):
    return any(part.casefold() == "openclaw-local" for part in Path(path).parts)


def available(root):
    try:
        return (not forbidden(root) and root.resolve(strict=True) == root and root.is_dir()
                and os.access(root, os.R_OK | os.X_OK))
    except (OSError, ValueError):
        return False


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ConfigError("配置存在重复字段。")
        value[key] = item
    return value


def load_config(path: Path, *, missing=False) -> ProjectConfig:
    try:
        if missing and not path.exists() and not path.is_symlink():
            return ProjectConfig(())
        if path.is_symlink() or path.stat().st_size > 65536:
            raise ConfigError("配置必须是非链接文件且不超过 64 KiB。")
        raw_bytes = path.read_bytes()
        value = json.loads(raw_bytes, object_pairs_hook=unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigError("配置不可读或 JSON 格式无效。") from exc
    if not isinstance(value, dict):
        raise ConfigError("配置必须是对象。")
    legacy = set(value) == {"projects"}
    if not legacy and (set(value) != {"version", "workspace_root", "revision", "projects", "operations"}
                       or type(value["version"]) is not int or value["version"] != 1
                       or type(value["revision"]) is not int or value["revision"] < 1):
        raise ConfigError("项目配置格式或版本无效。")
    if not isinstance(value["projects"], list) or len(value["projects"]) > 256 or legacy and not value["projects"]:
        raise ConfigError("projects 必须是有效列表，最多 256 项。")
    workspace, operations = None, ()
    if not legacy:
        workspace = canonical_record(value["workspace_root"])
        operations = value["operations"]
        if not isinstance(operations, list) or len(operations) > 128:
            raise ConfigError("项目请求记录无效。")
        ids = set()
        for operation in operations:
            if (not isinstance(operation, dict) or set(operation) != {"id", "fingerprint", "revision", "removed"}
                    or not isinstance(operation["id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", operation["id"])
                    or operation["id"] in ids or not isinstance(operation["fingerprint"], str)
                    or not re.fullmatch(r"[0-9a-f]{64}", operation["fingerprint"])
                    or type(operation["revision"]) is not int or not 1 <= operation["revision"] <= value["revision"]
                    or operation["removed"] != "" and not valid_alias(operation["removed"])):
                raise ConfigError("项目请求记录无效。")
            ids.add(operation["id"])
    projects = []
    aliases, roots = set(), set()
    for item in value["projects"]:
        if not isinstance(item, dict) or set(item) != {"alias", "root"}:
            raise ConfigError("项目只接受 alias、root 字段。")
        alias, raw = item["alias"], item["root"]
        if not valid_alias(alias):
            raise ConfigError("项目别名必须使用英文字母、数字、连字符或下划线。")
        if not isinstance(raw, str) or not Path(raw).expanduser().is_absolute():
            raise ConfigError("项目根目录必须是绝对路径。")
        if forbidden(Path(raw).expanduser()):
            raise ConfigError("该目录不在允许范围内。")
        if legacy:
            try:
                root = Path(raw).expanduser().resolve(strict=True)
            except (OSError, ValueError) as exc:
                raise ConfigError("项目根目录不可访问。") from exc
            if forbidden(root) or not root.is_dir():
                raise ConfigError("项目根目录必须是允许的目录。")
        else:
            root = canonical_record(raw)
        if alias in aliases or root in roots:
            raise ConfigError("项目别名和真实根目录不得重复。")
        aliases.add(alias)
        roots.add(root)
        projects.append(Project(alias, root))
    return ProjectConfig(tuple(projects), workspace, 0 if legacy else value["revision"],
                         tuple(operations), hashlib.sha256(raw_bytes).hexdigest())


def canonical_record(raw):
    if not isinstance(raw, str) or not raw or "\0" in raw:
        raise ConfigError("配置目录无效。")
    path = Path(raw)
    if not path.is_absolute() or str(path) != raw or ".." in path.parts or forbidden(path):
        raise ConfigError("配置目录须为允许的规范绝对路径。")
    return path


def load_projects(path: Path) -> tuple[Project, ...]:
    return load_config(path).projects


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
