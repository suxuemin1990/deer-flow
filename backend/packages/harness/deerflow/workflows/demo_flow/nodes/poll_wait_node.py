"""Async sleep + fake score (uses asyncio.sleep so we don't block the loop)."""

from __future__ import annotations

import asyncio
import random


async def poll_wait_node(state):
    await asyncio.sleep(2)
    current = state["current_round"]
    score = round(random.uniform(0.4, 0.9), 3)
    return {"history": [{"round": current, "score": score}]}
