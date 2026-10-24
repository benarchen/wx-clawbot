"""Explicit read-only iTerm2 connection probe, isolated from the main loop."""

import asyncio
import json


async def probe() -> dict:
    import iterm2

    connection = None
    try:
        connection = await asyncio.wait_for(iterm2.Connection.async_create(), 8)
        app = await asyncio.wait_for(iterm2.async_get_app(connection), 5)
        return {"status": "connected", "windows": len(app.windows),
                "terminals": sum(len(t.sessions) for w in app.windows for t in w.tabs)}
    except (OSError, TimeoutError) as exc:
        return {"status": "unavailable", "error_type": type(exc).__name__,
                "next_step": "核对 iTerm2 Settings → General → Magic → Enable Python API server 及脚本授权。"}
    except Exception as exc:
        return {"status": "failed", "error_type": type(exc).__name__}
    finally:
        if connection is not None:
            await connection.websocket.close()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(probe()), ensure_ascii=False))
