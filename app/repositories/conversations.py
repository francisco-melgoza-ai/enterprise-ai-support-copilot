import asyncio
from datetime import UTC, datetime
from typing import Protocol

from app.schemas.conversations import Conversation, ConversationMessage


class ConversationRepository(Protocol):
    async def create_conversation(self, conversation: Conversation) -> Conversation:
        """Persist a new conversation."""

    async def get_conversation(self, conversation_id: str) -> Conversation | None:
        """Return a conversation by id."""

    async def update_conversation(self, conversation: Conversation) -> Conversation:
        """Replace a stored conversation."""

    async def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation and its messages."""

    async def append_message(self, message: ConversationMessage) -> ConversationMessage:
        """Persist a message."""

    async def list_messages(self, conversation_id: str) -> list[ConversationMessage]:
        """Return messages ordered by creation time."""

    async def replace_messages(
        self,
        conversation_id: str,
        messages: list[ConversationMessage],
    ) -> None:
        """Replace all messages for a conversation."""

    async def active_conversation_count(self) -> int:
        """Return non-expired conversation count."""

    async def average_message_count(self) -> float:
        """Return average stored message count for active conversations."""


class InMemoryConversationRepository:
    def __init__(self) -> None:
        self._conversations: dict[str, Conversation] = {}
        self._messages: dict[str, list[ConversationMessage]] = {}
        self._lock = asyncio.Lock()

    async def create_conversation(self, conversation: Conversation) -> Conversation:
        async with self._lock:
            self._conversations[conversation.conversation_id] = conversation
            self._messages[conversation.conversation_id] = []
            return conversation

    async def get_conversation(self, conversation_id: str) -> Conversation | None:
        async with self._lock:
            self._remove_expired_locked()
            return self._conversations.get(conversation_id)

    async def update_conversation(self, conversation: Conversation) -> Conversation:
        async with self._lock:
            if conversation.conversation_id not in self._conversations:
                raise KeyError(conversation.conversation_id)
            self._conversations[conversation.conversation_id] = conversation
            return conversation

    async def delete_conversation(self, conversation_id: str) -> bool:
        async with self._lock:
            existed = conversation_id in self._conversations
            self._conversations.pop(conversation_id, None)
            self._messages.pop(conversation_id, None)
            return existed

    async def append_message(self, message: ConversationMessage) -> ConversationMessage:
        async with self._lock:
            if message.conversation_id not in self._conversations:
                raise KeyError(message.conversation_id)
            self._messages.setdefault(message.conversation_id, []).append(message)
            return message

    async def list_messages(self, conversation_id: str) -> list[ConversationMessage]:
        async with self._lock:
            self._remove_expired_locked()
            return sorted(
                self._messages.get(conversation_id, []),
                key=lambda message: message.created_at,
            )

    async def replace_messages(
        self,
        conversation_id: str,
        messages: list[ConversationMessage],
    ) -> None:
        async with self._lock:
            if conversation_id not in self._conversations:
                raise KeyError(conversation_id)
            self._messages[conversation_id] = sorted(
                messages,
                key=lambda message: message.created_at,
            )

    async def active_conversation_count(self) -> int:
        async with self._lock:
            self._remove_expired_locked()
            return len(self._conversations)

    async def average_message_count(self) -> float:
        async with self._lock:
            self._remove_expired_locked()
            if not self._conversations:
                return 0.0
            total_messages = sum(
                len(self._messages.get(conversation_id, []))
                for conversation_id in self._conversations
            )
            return total_messages / len(self._conversations)

    def _remove_expired_locked(self) -> None:
        now = datetime.now(UTC)
        expired_ids = [
            conversation_id
            for conversation_id, conversation in self._conversations.items()
            if conversation.expires_at <= now
        ]
        for conversation_id in expired_ids:
            self._conversations.pop(conversation_id, None)
            self._messages.pop(conversation_id, None)
