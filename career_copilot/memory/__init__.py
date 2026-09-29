"""What the assistant remembers about the user between turns.

Three pieces, deliberately separate:

- `storage.memory` stores rows and enforces the caps.
- `extract` decides what, out of a finished turn, was worth keeping.
- `recall` decides which of it belongs in the next prompt.

Storing and injecting are different limits and different judgements. Conflating
them is how a memory feature turns into a slowly growing prompt.
"""

from career_copilot.memory.extract import extract_facts, remember_turn
from career_copilot.memory.recall import recall_block

__all__ = ["extract_facts", "recall_block", "remember_turn"]
