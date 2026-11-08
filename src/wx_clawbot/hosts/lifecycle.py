"""A replaceable iTerm2 connection; authentication never blocks the event loop."""

import asyncio
import os
from pathlib import Path

from .connection import close_connection
from .process import read_process


class HostUnavailable(ConnectionError):
    def __init__(self, phase="connect"):
        self.phase = phase
        messages = {
            "not_running": "iTerm2 尚未启动；可用 /cd 或 /new 按需启动。/sessions 仅查询，不启动应用。",
            "authentication": "iTerm2 连接／授权阶段未完成或超时，请在电脑端核对授权；不能据此判断 API 未启用。",
            "launch": "iTerm2 启动未确认，请在电脑端核对；没有创建或执行 Codex 任务。",
            "changed": "iTerm2 连接已变化，请刷新会话后重试；没有自动重放操作。",
        }
        super().__init__(messages.get(phase, "iTerm2 API 连接不可用或超时，请核对应用及 API 授权后刷新会话。"))


async def run_process(arguments, *, timeout=8, limit=4096):
    """Bound both output and lifetime, including cancellation of our own child."""
    process = await asyncio.create_subprocess_exec(
        *arguments, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        async with asyncio.timeout(timeout):
            output = await process.stdout.read(limit + 1)
            if len(output) > limit:
                raise ValueError("Child output exceeds bound")
            code = await process.wait()
            return code, output
    finally:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 1)
            except TimeoutError:
                process.kill()
                await asyncio.wait_for(process.wait(), 1)


class ItermBackend:
    async def _open_websocket(self, headers, *, timeout=5):
        import iterm2
        from iterm2.connection import _subprotocols, websockets_client

        socket = iterm2.Connection()._unix_domain_socket_path()
        options = dict(ping_interval=None, close_timeout=0, open_timeout=timeout,
                       extra_headers=headers, subprotocols=_subprotocols(),
                       max_size=4 * 1024 * 1024, max_queue=2)
        if Path(socket).exists():
            return await websockets_client.unix_connect(socket, "ws://localhost/", **options)
        return await websockets_client.connect("ws://localhost:1912", **options)

    async def _probe_auth_transport(self):
        from iterm2.connection import _headers

        headers = _headers()
        headers.pop("x-iterm2-cookie", None)
        headers.pop("x-iterm2-key", None)
        headers.update({"x-iterm2-disable-auth-ui": "true", "x-iterm2-advisory-name": "wx-clawbot"})
        try:
            websocket = await self._open_websocket(headers, timeout=2)
        except Exception as exc:
            # An HTTP response (normally 401) proves transport responsiveness,
            # never authorization. No cookies, UI prompt or API call is used.
            if type(getattr(exc, "status_code", None)) is int:
                return
            raise HostUnavailable("connect") from None
        try:
            await asyncio.wait_for(websocket.close(), 1)
        except (OSError, TimeoutError):
            raise HostUnavailable("connect") from None

    async def wait_ready(self, identity, *, timeout=5):
        """Wait for this process's API without requesting authorization or creating terminals."""
        try:
            async with asyncio.timeout(timeout):
                delay = .1
                while True:
                    if await self.identity() != identity:
                        raise HostUnavailable("changed")
                    try:
                        await self._probe_auth_transport()
                    except HostUnavailable as exc:
                        if exc.phase != "connect":
                            raise
                    else:
                        if await self.identity() != identity:
                            raise HostUnavailable("changed")
                        return
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, .5)
        except TimeoutError:
            raise HostUnavailable("connect") from None

    async def identity(self):
        code, output = await run_process(["/usr/bin/pgrep", "-x", "iTerm2"], timeout=2)
        if code == 1:
            return None
        if code or len(output.split()) != 1:
            raise HostUnavailable("process")
        try:
            identity = read_process(int(output.strip()))
        except ValueError:
            identity = None
        if identity is None or Path(identity.executable).name != "iTerm2":
            raise HostUnavailable("process")
        return identity

    async def launch(self):
        # Suppress the startup-only default window in this process's volatile
        # argument domain. Keep restoration and later Dock opens unchanged.
        # A noop initial event avoids the separate open/reopen window request.
        script = '''ObjC.import("AppKit");
const workspace = $.NSWorkspace.sharedWorkspace;
const url = workspace.URLForApplicationWithBundleIdentifier("com.googlecode.iterm2");
if (url.isNil()) throw new Error("iTerm2 application is unavailable");
const config = $.NSWorkspaceOpenConfiguration.configuration;
config.activates = false;
config.arguments = $(["-OpenNewWindowAtStartup", "NO"]);
config.appleEvent = $.NSAppleEventDescriptor.appleEventWithEventClassEventIDTargetDescriptorReturnIDTransactionID(
    0x61736372, 0x6e6f6f70, $(), -1, 0);
let done = false, failed = false;
workspace.openApplicationAtURLConfigurationCompletionHandler(url, config, function(app, error) {
    failed = !app || app.isNil();
    done = true;
});
while (!done) $.NSRunLoop.currentRunLoop.runUntilDate($.NSDate.dateWithTimeIntervalSinceNow(0.05));
if (failed) throw new Error("iTerm2 application launch failed");'''
        code, _ = await run_process([
            "/usr/bin/osascript", "-l", "JavaScript", "-e", script,
        ])
        if code:
            raise HostUnavailable("launch")

    async def connect(self):
        # SDK 2.30 async_create calls synchronous AppleScript before its first
        # await. Acquire fresh credentials in a killable child instead. Mirror
        # its verified headers and reader without changing process environment.
        import iterm2
        from iterm2.connection import _headers

        # Do not request Automation consent from an unresponsive API server.
        await self._probe_auth_transport()
        script = ('if application id "com.googlecode.iterm2" is running then\n'
                  'tell application id "com.googlecode.iterm2" to request cookie and key '
                  'for app named "wx-clawbot"\nend if')
        try:
            code, output = await run_process(["/usr/bin/osascript", "-e", script])
            parts = output.decode("ascii").strip().split(" ")
            if code or len(parts) != 2 or any(not p or any(ord(c) < 33 or ord(c) > 126 for c in p) for p in parts):
                raise ValueError("Authentication response invalid")
        except TimeoutError as exc:
            # A frozen app cannot answer the authorization AppleEvent either.
            # Keep retrying transport outages, while a responsive API with a
            # pending/denied authorization must not create repeated prompts.
            await self._probe_auth_transport()
            raise HostUnavailable("authentication") from exc
        except (OSError, ValueError) as exc:
            raise HostUnavailable("authentication") from exc

        class Connection(iterm2.Connection):
            async def _async_dispatch_forever(self, connection, loop):
                # Mirror the pinned SDK dispatch loop, but never print raw
                # transport/protobuf exceptions to a user's terminal.
                from iterm2.connection import ServerOriginatedMessage
                self._Connection__tasks = []
                try:
                    while True:
                        data = await self.websocket.recv()
                        self._collect_garbage()
                        message = ServerOriginatedMessage()
                        message.ParseFromString(data)
                        future = self._get_receiver_future(message)
                        if future is not None:
                            self.set_message_in_future(loop, message, future)
                        else:
                            task = asyncio.create_task(self._async_dispatch_to_helper(message))
                            self._Connection__tasks.append(task)
                            task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
                except asyncio.CancelledError:
                    return
                except Exception:
                    raise HostUnavailable("reader") from None

            async def async_dispatch_until_id(self, request_id):
                reader = getattr(self, "_Connection__dispatch_forever_future")
                work = asyncio.create_task(super().async_dispatch_until_id(request_id))
                try:
                    done, _ = await asyncio.wait((work, reader), timeout=5, return_when=asyncio.FIRST_COMPLETED)
                    if work in done:
                        return work.result()
                    raise HostUnavailable("rpc")
                finally:
                    work.cancel()
                    await asyncio.gather(work, return_exceptions=True)
                    receivers = getattr(self, "_Connection__receivers")
                    receivers[:] = [(match, future) for match, future in receivers if not future.done()]

        connection = Connection()
        headers = _headers()
        headers.update({"x-iterm2-cookie": parts[0], "x-iterm2-key": parts[1],
                        "x-iterm2-advisory-name": "wx-clawbot"})
        try:
            connection.websocket = await self._open_websocket(headers)
            reader = asyncio.create_task(connection._async_dispatch_forever(connection, asyncio.get_running_loop()))
            setattr(connection, "_Connection__dispatch_forever_future", reader)
            return connection
        except Exception as exc:
            phase = "authentication" if getattr(exc, "status_code", None) == 401 else "connect"
            raise HostUnavailable(phase) from None

    async def probe(self, connection):
        import iterm2

        reader = getattr(connection, "_Connection__dispatch_forever_future", None)
        if reader is not None and reader.done():
            raise HostUnavailable("reader")
        await iterm2.async_get_app(connection)


class HostLifecycle:
    def __init__(self, backend=None, *, rpc_timeout=5):
        self.backend = backend or ItermBackend()
        self.rpc_timeout = rpc_timeout
        self.state, self.phase = "not_running", "not_running"
        self.generation = 0
        self._connection = self.identity = None
        self.lock = asyncio.Lock()
        self.rpc_lock = asyncio.Lock()
        self.authentication_blocked = False

    @property
    def connection(self):
        if self._connection is None:
            raise HostUnavailable(self.phase)
        reader = getattr(self._connection, "_Connection__dispatch_forever_future", None)
        if reader is not None and reader.done():
            raise HostUnavailable("reader")
        return self._connection

    def report(self):
        return {"state": self.state, "phase": self.phase, "generation": self.generation}

    async def disconnect(self, phase="connect", *, expected=None):
        if expected is not None and expected != self.generation:
            return
        old, self._connection = self._connection, None
        self.rpc_lock = asyncio.Lock()
        self.generation += 1
        self.state, self.phase = "unavailable", phase
        if old is not None:
            await close_connection(old)

    async def ensure(self, *, launch=False, explicit=False):
        async with self.lock:
            identity = await self.backend.identity()
            if identity is None and launch:
                self.state, self.phase = "connecting", "launch"
                try:
                    await self.backend.launch()
                    async with asyncio.timeout(5):
                        while identity is None:
                            await asyncio.sleep(.1)
                            identity = await self.backend.identity()
                except (OSError, TimeoutError) as exc:
                    raise HostUnavailable("launch") from exc
            if identity is None:
                if self._connection is not None:
                    await self.disconnect("not_running")
                self.identity = None
                self.authentication_blocked = False
                self.state, self.phase = "not_running", "not_running"
                raise HostUnavailable("not_running")
            changed = identity != self.identity
            if changed:
                await self.disconnect("changed")
                self.identity = identity
                self.authentication_blocked = False
            if self._connection is not None:
                try:
                    await self.call(self.backend.probe)
                    return self.generation
                except HostUnavailable:
                    pass
            if self.authentication_blocked and not explicit:
                raise HostUnavailable("authentication")
            self.state, self.phase = "connecting", "authentication"
            try:
                async with asyncio.timeout(15):
                    if launch:
                        self.phase = "connect"
                        await self.backend.wait_ready(identity)
                        self.phase = "authentication"
                    connection = await self.backend.connect()
                self._connection = connection
                self.generation += 1
                self.state, self.phase = "verifying", "discover"
                await self.call(self.backend.probe)
                self.authentication_blocked = False
                return self.generation
            except HostUnavailable as exc:
                if exc.phase == "authentication":
                    self.authentication_blocked = True
                await self.disconnect(exc.phase)
                raise
            except (OSError, TimeoutError) as exc:
                await self.disconnect("connect")
                raise HostUnavailable("connect") from exc

    async def call(self, work):
        generation = self.generation
        try:
            connection = self.connection
            async with asyncio.timeout(self.rpc_timeout):
                async with self.rpc_lock:
                    result = await work(connection)
            if generation != self.generation or self._connection is not connection:
                raise HostUnavailable("changed")
            return result
        except asyncio.CancelledError:
            # An interrupted RPC may still be awaiting an SDK response. Retire
            # that connection; never reuse it to replay a possible mutation.
            await self.disconnect("changed", expected=generation)
            raise
        except Exception as exc:
            await self.disconnect(getattr(exc, "phase", "rpc"), expected=generation)
            if isinstance(exc, HostUnavailable):
                raise
            raise HostUnavailable("rpc") from exc

    def verified(self, generation):
        if generation != self.generation or self._connection is None:
            raise HostUnavailable("changed")
        self.state, self.phase = "ready", "ready"

    async def close(self):
        await self.disconnect("stopped")
