"""Explicit read-only iTerm2 connection probe, isolated from the main loop."""

import asyncio
import json

from .connection import close_connection

async def probe() -> dict:
    import iterm2

    connection = None
    phase = "connect"
    try:
        connection = await asyncio.wait_for(iterm2.Connection.async_create(), 8)
        phase = "list_sessions"
        app = await asyncio.wait_for(iterm2.async_get_app(connection), 5)
        return {"status": "connected", "windows": len(app.windows),
                "terminals": sum(len(t.sessions) for w in app.windows for t in w.tabs)}
    except (OSError, TimeoutError) as exc:
        return {"status": "unavailable", "error_type": type(exc).__name__,
                "phase": phase,
                "next_step": (
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
    print(json.dumps(asyncio.run(probe()), ensure_ascii=False))
