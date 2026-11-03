"""Repository/worktree admission, independent of the native execution queue."""

import asyncio
import shutil
from pathlib import Path


class AdmissionConflict(str):
    def __new__(cls, reason, blockers=()):
        value = super().__new__(cls, reason)
        value.blockers = tuple(blockers)
        return value


async def repository_key(cwd: Path, project_root: Path | None) -> str:
    executable = shutil.which("git")
    if executable is None:
        raise ValueError("Git is required to verify repository/worktree conflicts")
    process = await asyncio.create_subprocess_exec(executable, "-C", str(cwd), "rev-parse",
        "--path-format=absolute", "--git-common-dir", stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, limit=8192)
    try:
        output, _ = await asyncio.wait_for(process.communicate(), 2)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    if process.returncode == 0:
        if len(output) > 8192:
            raise ValueError("Repository identity exceeds its bound")
        value = output.decode().removesuffix("\n")
        path = Path(value)
        if not path.is_absolute() or "\n" in value or not path.is_dir():
            raise ValueError("Repository common directory is not verifiable")
        return "git:" + str(path.resolve(strict=True))
    # A failed Git lookup in a repository is not proof of independent directories.
    if any((parent / ".git").exists() for parent in (cwd, *cwd.parents)):
        raise ValueError("Repository/worktree identity lookup failed")
    if project_root is None:
        raise ValueError("Unregistered non-Git project has no verified root")
    return "directory:" + str(project_root.resolve(strict=True))


async def conflict(task, active, catalog, projects):
    target = task["target"]
    holds = [t for t in active if t["id"] != task["id"] and t["state"] not in {"received", "prepared"}]
    aliases = {t["target"]["project_alias"] for t in holds if t["target"].get("source") != "external"}
    if target["project_alias"] not in aliases and len(aliases) >= 2:
        return AdmissionConflict("已有两个桥接活动项目", (t["id"] for t in holds))
    keys = {target["cwd"]: target["repository"]}

    async def key(record):
        cwd = record["cwd"]
        if cwd not in keys:
            project = projects.get(record["project_alias"])
            if project is None and record.get("repository"):
                # A removed registration does not release its old unknown task.
                keys[cwd] = record["repository"]
            else:
                try:
                    keys[cwd] = await repository_key(Path(cwd), project.root if project else None)
                except ValueError:
                    if project is not None:
                        raise
                    keys[cwd] = None
        return keys[cwd]

    blocked = []
    for other in holds:
        destination = other["target"]
        if destination["session_id"] == target["session_id"]:
            continue  # Same native session uses its own FIFO queue.
        identity = await key(destination)
        if identity is None:
            return AdmissionConflict("旧项目任务的仓库身份无法复验，请先核对未知任务", [other["id"]])
        if destination["project_alias"] == target["project_alias"] or identity == target["repository"]:
            blocked.append(other["id"])
    if blocked:
        return AdmissionConflict("同项目或同仓库的另一会话仍有未结束任务", blocked)
    # External clients remain autonomous. Detect their current activity instead of
    # claiming that a local mutex can prevent a desktop user from starting work.
    for session in tuple(catalog.sessions.values()):
        destination = session.target
        if destination.session_id == target["session_id"]:
            continue
        same_project = destination.project_alias == target["project_alias"]
        record = {"cwd": str(destination.cwd), "project_alias": destination.project_alias}
        if same_project or await key(record) == target["repository"]:
            thread = await catalog.agent.inspect(session.binding.thread_id)
            if thread.get("status", {}).get("type") == "active":
                return "同项目或同仓库检测到其他桌面会话正在执行"
    return None
