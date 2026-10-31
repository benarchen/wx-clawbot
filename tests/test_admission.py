import asyncio
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from pathlib import Path

from wx_clawbot.admission import repository_key, conflict


class RemovedRegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def check(self, destination, resolver):
        target = {'cwd': '/fixture/new', 'repository': 'git:/fixture/shared',
                  'project_alias': 'new', 'session_id': 'new-session'}
        task = {'id': 'new-task', 'target': target}
        old = {'id': 'old-task', 'state': 'unknown', 'target': destination}
        with patch('wx_clawbot.admission.repository_key', resolver):
            return await conflict(task, [old, task], SimpleNamespace(sessions={}), {})

    async def test_removed_project_frozen_repository_still_blocks_same_repository(self):
        resolve = AsyncMock(side_effect=AssertionError('Frozen identity must be kept'))
        reason = await self.check({'cwd': '/fixture/old', 'repository': 'git:/fixture/shared',
                                  'project_alias': 'removed', 'session_id': 'old-session'}, resolve)
        self.assertIn('同仓库', reason)
        resolve.assert_not_awaited()

    async def test_legacy_removed_project_can_only_use_verified_git_identity(self):
        resolve = AsyncMock(return_value='git:/fixture/other')
        reason = await self.check({'cwd': '/fixture/old', 'project_alias': 'removed',
                                  'session_id': 'old-session'}, resolve)
        self.assertIsNone(reason)
        resolve.assert_awaited_once_with(Path('/fixture/old'), None)

    async def test_unverifiable_removed_project_blocks_without_crashing(self):
        resolve = AsyncMock(side_effect=ValueError('No registered root'))
        reason = await self.check({'cwd': '/fixture/old', 'project_alias': 'removed',
                                  'session_id': 'old-session'}, resolve)
        self.assertIn('无法复验', reason)


@unittest.skipUnless(shutil.which("git"), "Local Git required for repository/worktree identity tests")
class RepositoryIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        parent = Path(__file__).resolve().parents[1] / ".tmp" / "admission-tests"
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    async def git(self, cwd, *args):
        process = await asyncio.create_subprocess_exec("git", "-c", "core.hooksPath=/dev/null",
            "-c", "commit.gpgsign=false", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
            "-C", str(cwd), *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        output, error = await process.communicate()
        self.assertEqual(process.returncode, 0, error.decode())
        return output

    async def test_worktrees_share_common_identity_and_separate_repositories_do_not(self):
        first, second, linked = (self.root / name for name in ("first", "second", "linked"))
        for path in (first, second):
            path.mkdir()
            await self.git(path, "init", "--initial-branch=main")
        await self.git(first, "commit", "--allow-empty", "-m", "fixture")
        await self.git(first, "worktree", "add", "-b", "fixture-linked", str(linked))
        self.assertEqual(await repository_key(first, first), await repository_key(linked, linked))
        self.assertNotEqual(await repository_key(first, first), await repository_key(second, second))
        child = first / "nested directory"
        child.mkdir()
        self.assertEqual(await repository_key(first, first), await repository_key(child, first))

    async def test_special_characters_are_literal_and_invalid_git_metadata_fails_closed(self):
        project = self.root / "project ' $(touch NEVER)"
        project.mkdir()
        await self.git(project, "init")
        self.assertTrue((await repository_key(project, project)).startswith("git:"))
        self.assertFalse((self.root / "NEVER").exists())
        broken = self.root / "broken"
        broken.mkdir()
        (broken / ".git").write_text("gitdir: missing\n")
        with self.assertRaises(ValueError):
            await repository_key(broken, broken)
