from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


SERVERS = {
    "project": {
        "module": "budget_pipeline.servers.project",
        "title": "Проект: git и безопасная работа с файлами",
    },
    "support": {
        "module": "budget_pipeline.servers.support",
        "title": "Поддержка: пользователи и тикеты",
    },
}


class McpBridge:
    def __init__(self, servers: list[str] | None = None):
        self.names = servers or list(SERVERS)
        self.loop: asyncio.AbstractEventLoop | None = None
        self.thread: threading.Thread | None = None
        self.sessions: dict[str, ClientSession] = {}
        self.tools: dict[str, list[dict]] = {}
        self.errors: dict[str, str] = {}
        self._ready = threading.Event()
        self._stop: asyncio.Event | None = None

    def start(self) -> list[dict]:
        if self.thread:
            return self.status()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self._ready.wait(timeout=35)
        return self.status()

    def _run(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._serve())
        finally:
            self.loop.close()

    async def _serve(self) -> None:
        self._stop = asyncio.Event()
        async with AsyncExitStack() as stack:
            for name in self.names:
                try:
                    parameters = StdioServerParameters(
                        command=sys.executable,
                        args=["-m", SERVERS[name]["module"]],
                        env=dict(os.environ),
                    )
                    read_stream, write_stream = await stack.enter_async_context(stdio_client(parameters))
                    session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
                    await asyncio.wait_for(session.initialize(), timeout=15)
                    listed = await asyncio.wait_for(session.list_tools(), timeout=15)
                    self.sessions[name] = session
                    self.tools[name] = [
                        {
                            "name": tool.name,
                            "description": tool.description or "",
                            "input_schema": tool.inputSchema or {"type": "object", "properties": {}},
                        }
                        for tool in listed.tools
                    ]
                except Exception as error:
                    self.errors[name] = f"{type(error).__name__}: {error}"
            self._ready.set()
            await self._stop.wait()

    def status(self) -> list[dict]:
        return [
            {
                "server": name,
                "title": SERVERS[name]["title"],
                "connected": name in self.sessions,
                "tools": len(self.tools.get(name, [])),
                "error": self.errors.get(name, ""),
            }
            for name in self.names
        ]

    async def _call(self, server: str, name: str, arguments: dict) -> dict:
        result = await asyncio.wait_for(self.sessions[server].call_tool(name, arguments), timeout=60)
        texts = [getattr(item, "text", "") for item in (result.content or [])]
        joined = "\n".join(text for text in texts if text)
        if getattr(result, "isError", False):
            raise RuntimeError(joined or f"{server}.{name}: MCP error")
        structured = getattr(result, "structuredContent", None)
        if structured:
            return structured
        try:
            return json.loads(joined)
        except (json.JSONDecodeError, TypeError):
            return {"text": joined}

    def call(self, server: str, name: str, arguments: dict | None = None) -> dict:
        if not self.loop or server not in self.sessions:
            raise RuntimeError(f"MCP server not connected: {server}")
        future = asyncio.run_coroutine_threadsafe(
            self._call(server, name, arguments or {}), self.loop
        )
        return future.result(timeout=70)

    def stop(self) -> None:
        if self.loop and self._stop:
            self.loop.call_soon_threadsafe(self._stop.set)
        if self.thread:
            self.thread.join(timeout=10)
        self.thread = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.stop()

