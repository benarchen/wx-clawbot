"""Lifecycle cleanup for the explicitly pinned iTerm2 SDK 2.30 connection."""

import asyncio


async def close_connection(connection) -> None:
    from iterm2.app import App, invalidate_app

    # Our explicit reader cancellation bypasses the SDK's disconnect callback.
    # Do not let a later connection reuse this closed connection's app singleton.
    if App.instance is not None and App.instance.connection is connection:
        invalidate_app()
    # SDK 2.30 async_create starts this task but exposes no async close method.
    # Cancel its reader before closing the socket, as SDK run_until_complete does.
    task = getattr(connection, "_Connection__dispatch_forever_future", None)
    if task is not None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    try:
        await asyncio.wait_for(connection.websocket.close(), 2)
    except TimeoutError:
        pass
