"""Repository/worktree admission, independent of the native execution queue."""

import asyncio
import shutil
from pathlib import Path


async def repository_key(cwd: Path, project_root: Path) -> str:
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
    return "directory:" + str(project_root.resolve(strict=True))


async def conflict(task, active, catalog, projects):
    target = task["target"]
    holds = [t for t in active if t["id"] != task["id"] and t["state"] not in {"received", "prepared"}]
    aliases = {t["target"]["project_alias"] for t in holds if t["target"].get("source") != "external"}
    if target["project_alias"] not in aliases and len(aliases) >= 2:
        return "已有两个桥接活动项目"
    keys = {target["cwd"]: target["repository"]}

    async def key(record):
        cwd = record["cwd"]
        if cwd not in keys:
            keys[cwd] = await repository_key(Path(cwd), projects[record["project_alias"]].root)
        return keys[cwd]

    for other in holds:
        destination = other["target"]
        if destination["session_id"] == target["session_id"]:
            continue  # Same native session uses its own FIFO queue.
        if destination["project_alias"] == target["project_alias"] or await key(destination) == target["repository"]:
            return "同项目或同仓库的另一会话仍有未结束任务"
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
