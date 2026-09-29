"""Conversation history, kept in the process that is serving the conversation.

The client sends a thread id and one message; it does not send the history
back. Something has to hold the earlier turns, and for a single-user desktop
application that something is a dictionary.

Two bounds keep it from becoming a leak: a thread remembers a fixed number of
recent messages, and the store remembers a fixed number of threads, evicting
the least recently used. Both are deliberately small. Long-term memory is a
different thing entirely - facts that survive a restart, extracted on purpose -
and it arrives in its own phase rather than by letting this grow.

Restarting the server forgets every conversation. That is the honest cost of
not having a store yet, and it is written down here rather than discovered.

Each thread also carries a lock. Two turns on one thread would otherwise
interleave their messages and their usage accounting; the API serialises them
instead of racing.
"""

from __future__ import annotations

import threading
from collections import OrderedDict, deque
from dataclasses import dataclass, field

from career_copilot.core.llm_types import ChatMessage

__all__ = ["MAX_MESSAGES", "MAX_THREADS", "Thread", "clear", "get"]

#: Messages kept per thread. A user turn and its answer are two, so this is
#: roughly the last eight exchanges - enough to resolve "it" and "that one",
#: short enough that the prompt does not grow without limit.
MAX_MESSAGES = 16

#: Threads kept at once. Beyond this the least recently used is dropped.
MAX_THREADS = 32


@dataclass
class Thread:
    """One conversation: its recent messages and a lock over them."""

    id: str
    messages: deque[ChatMessage] = field(default_factory=lambda: deque(maxlen=MAX_MESSAGES))
    lock: threading.Lock = field(default_factory=threading.Lock)

    def history(self) -> list[ChatMessage]:
        """A snapshot the agent can hold while the deque keeps changing."""
        return list(self.messages)

    def record(self, question: str, answer: str) -> None:
        self.messages.append({"role": "user", "content": question})
        self.messages.append({"role": "assistant", "content": answer})


_THREADS: OrderedDict[str, Thread] = OrderedDict()
_REGISTRY_LOCK = threading.Lock()


def get(thread_id: str) -> Thread:
    """The thread with this id, creating it if this is its first message."""
    with _REGISTRY_LOCK:
        thread = _THREADS.get(thread_id)
        if thread is None:
            thread = Thread(id=thread_id)
            _THREADS[thread_id] = thread
            while len(_THREADS) > MAX_THREADS:
                _THREADS.popitem(last=False)
        else:
            _THREADS.move_to_end(thread_id)
        return thread


def clear() -> None:
    """Forget every thread. For tests, and for a signed-out session later."""
    with _REGISTRY_LOCK:
        _THREADS.clear()
