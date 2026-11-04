"""Explicit read-only iTerm2 connection probe, isolated from the main loop."""

import asyncio
import json

from .connection import close_connection
from .lifecycle import ItermBackend, HostUnavailable

async def probe() -> dict:
    import iterm2

    connection = None
    phase = "connect"
    try:
        backend = ItermBackend()
        if await backend.identity() is None:
            return {"status": "unavailable", "phase": "not_running", "next_step": "iTerm2 尚未启动；诊断不会拉起应用。"}
        connection = await backend.connect()
        phase = "list_sessions"
        app = await asyncio.wait_for(iterm2.async_get_app(connection), 5)
        return {"status": "connected", "windows": len(app.windows),
                "terminals": sum(len(t.sessions) for w in app.windows for t in w.tabs)}
    except (OSError, TimeoutError, HostUnavailable) as exc:
        return {"status": "unavailable", "error_type": type(exc).__name__,
                "phase": exc.phase if isinstance(exc, HostUnavailable) else phase,
                "next_step": (
                    str(exc) if isinstance(exc, HostUnavailable) else
                    "API 请求超时；检查 iTerm2 是否有等待处理的模态提示，不能据此判断 API 未启用。"
                    if isinstance(exc, TimeoutError) else
                    "API 连接失败；核对 Enable Python API server、脚本授权与实际 SDK 端点。"
                )}
    except Exception as exc:
        return {"status": "failed", "error_type": type(exc).__name__}
    finally:
        if connection is not None:
            await close_connection(connection)


if __name__ == "__main__":
    from ..release import verify_active
    verify_active()
    print(json.dumps(asyncio.run(probe()), ensure_ascii=False))
