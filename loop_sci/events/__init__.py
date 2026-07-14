"""Re-export vendored EventBus, NullBus, Event, and event-type constants.

Usage::

    from loop_sci.events import EventBus, NullBus, Event
    from loop_sci.events import IDEA_PROPOSED, SESSION_START

Do NOT import from _vendor directly — this module is the public face.
"""

from loop_sci._vendor.arbor.events.bus import Event, EventBus, NullBus
from loop_sci._vendor.arbor.events.types import (
    IDEA_COMPLETED,
    IDEA_MERGED,
    IDEA_PROPOSED,
    IDEA_PRUNED,
    EXECUTOR_START,
    EXECUTOR_END,
    SESSION_START,
    SESSION_END,
)

__all__ = [
    "Event",
    "EventBus",
    "NullBus",
    "IDEA_PROPOSED",
    "IDEA_COMPLETED",
    "IDEA_PRUNED",
    "IDEA_MERGED",
    "EXECUTOR_START",
    "EXECUTOR_END",
    "SESSION_START",
    "SESSION_END",
]
