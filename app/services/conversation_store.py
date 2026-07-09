"""In-memory store for local testing conversations.

Keeps an in-progress local-test conversation's session, scenario, and state
machine alive between the stateless HTTP calls to ``/conversation/test/start``
and ``/conversation/test/message`` — plain HTTP has no connection to hang state
off of the way a WebSocket does, so something has to remember it between
requests. Process-local, self-pruning (an entry is discarded once its
conversation ends): a convenience for local development and testing, not a
production session store.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.scenario import Scenario
from app.models.session import CallSession
from app.state_machine.machine import ConversationStateMachine


@dataclass
class ConversationEntry:
    """One in-progress local-test conversation."""

    session: CallSession
    scenario: Scenario
    machine: ConversationStateMachine


class InMemoryConversationStore:
    """Process-local registry of in-progress local-test conversations."""

    def __init__(self) -> None:
        """Start with an empty registry."""
        self._entries: dict[str, ConversationEntry] = {}

    def create(
        self,
        conversation_id: str,
        session: CallSession,
        scenario: Scenario,
        machine: ConversationStateMachine,
    ) -> None:
        """Register a newly-started conversation.

        Args:
            conversation_id: Unique id the caller will use for every subsequent turn.
            session: The freshly-created call session.
            scenario: The flow this conversation is running.
            machine: The state machine driving this conversation.
        """
        self._entries[conversation_id] = ConversationEntry(session, scenario, machine)

    def get(self, conversation_id: str) -> ConversationEntry | None:
        """Look up an in-progress conversation.

        Args:
            conversation_id: The id returned by :meth:`create`.

        Returns:
            The matching entry, or ``None`` if unknown or already ended.
        """
        return self._entries.get(conversation_id)

    def discard(self, conversation_id: str) -> None:
        """Remove a conversation, e.g. once it has reached a terminal state."""
        self._entries.pop(conversation_id, None)
