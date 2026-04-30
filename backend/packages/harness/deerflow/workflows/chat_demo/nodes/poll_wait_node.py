"""Async sleep so injection has a real window."""

from __future__ import annotations

import asyncio


async def poll_wait_node(state):
    await asyncio.sleep(4)
    return {}
