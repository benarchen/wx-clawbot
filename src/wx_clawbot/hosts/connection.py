"""Lifecycle cleanup for the explicitly pinned iTerm2 SDK 2.30 connection."""

import asyncio


async def close_connection(connection) -> None:
    from iterm2.app import App, invalidate_app
    from iterm2 import notifications
    from iterm2.connection import gDisconnectCallbacks
    from iterm2.session import Session
    from iterm2.tab import Tab
    from iterm2.window import Window
    from iterm2 import tmux

    # Our explicit reader cancellation bypasses the SDK's disconnect callback.
    # Do not let a later connection reuse this closed connection's app singleton.
    app = App.instance or getattr(Session, "delegate", None)
    if app is not None and getattr(app, "connection", None) is connection:
        for key, callback in getattr(app, "tokens", ()):
            notifications._unregister_notification_handler_impl(key, callback)
            if not notifications._handlers.get(key):
                notifications._handlers.pop(key, None)
        for owner in (Session, Tab, Window):
            if getattr(owner, "delegate", None) is app:
                owner.delegate = None
        if getattr(tmux, "gDELEGATE", None) is app:
            tmux.gDELEGATE = None
        gDisconnectCallbacks[:] = [callback for callback in gDisconnectCallbacks if callback is not invalidate_app]
    if App.instance is not None and App.instance.connection is connection:
        invalidate_app()
    # SDK 2.30 async_create starts this task but exposes no async close method.
    # Cancel its reader before closing the socket, as SDK run_until_complete does.
    task = getattr(connection, "_Connection__dispatch_forever_future", None)
    if task is not None:
        task.cancel()
        try:
            await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 1)
        except TimeoutError:
            pass
    for _, future in getattr(connection, "_Connection__receivers", ()):
        future.cancel()
    helpers = tuple(getattr(connection, "_Connection__tasks", ()))
    for helper in helpers:
        helper.cancel()
    if helpers:
        try:
            await asyncio.wait_for(asyncio.gather(*helpers, return_exceptions=True), 1)
        except TimeoutError:
            pass
    try:
        await asyncio.wait_for(connection.websocket.close(), 2)
    except TimeoutError:
        transport = getattr(connection.websocket, "transport", None)
        if transport:
            transport.abort()
