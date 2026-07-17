import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

from app.core.auth import AuthenticatedPrincipal, SupportRole
from app.core.metrics import (
    record_conversation_created,
    record_conversation_deleted,
    record_conversation_message_added,
    record_conversation_summary_generated,
)
from app.core.tracing import get_tracer, record_span_exception, set_span_attributes
from app.repositories.conversations import ConversationRepository
from app.schemas.conversations import (
    Conversation,
    ConversationMemoryContext,
    ConversationMessage,
    ConversationRole,
)

logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)


class ConversationServiceError(Exception):
    """Base class for conversation service failures."""


class ConversationNotFoundError(ConversationServiceError):
    """Raised when a conversation is missing or expired."""


class ConversationAccessDeniedError(ConversationServiceError):
    """Raised when a principal does not own a conversation."""


class ConversationSummarizer(Protocol):
    async def summarize(
        self,
        *,
        existing_summary: str | None,
        messages: Sequence[ConversationMessage],
    ) -> str:
        """Summarize older conversation turns."""


class MockConversationSummarizer:
    async def summarize(
        self,
        *,
        existing_summary: str | None,
        messages: Sequence[ConversationMessage],
    ) -> str:
        role_counts: dict[str, int] = {}
        for message in messages:
            role_counts[message.role.value] = role_counts.get(message.role.value, 0) + 1
        counts = ", ".join(
            f"{role}:{count}" for role, count in sorted(role_counts.items())
        )
        snippets = "; ".join(
            f"{message.role.value}: {_snippet(message.content)}"
            for message in messages[:3]
        )
        prefix = f"{existing_summary} " if existing_summary else ""
        return (
            f"{prefix}Summarized {len(messages)} older messages ({counts}). "
            f"Key context: {snippets}."
        ).strip()


class MemoryManager:
    def __init__(
        self,
        *,
        summarizer: ConversationSummarizer,
        summary_threshold: int,
        max_recent_messages: int,
    ) -> None:
        if summary_threshold <= 0:
            raise ValueError("summary_threshold must be positive.")
        if max_recent_messages <= 0:
            raise ValueError("max_recent_messages must be positive.")
        if summary_threshold <= max_recent_messages:
            raise ValueError(
                "summary_threshold must be greater than max_recent_messages."
            )
        self._summarizer = summarizer
        self._summary_threshold = summary_threshold
        self._max_recent_messages = max_recent_messages

    async def maybe_summarize(
        self,
        *,
        conversation: Conversation,
        messages: list[ConversationMessage],
    ) -> tuple[Conversation, list[ConversationMessage], bool]:
        if len(messages) <= self._summary_threshold:
            return conversation, messages, False

        with tracer.start_as_current_span("conversation.summarize") as span:
            older_messages = messages[: -self._max_recent_messages]
            recent_messages = messages[-self._max_recent_messages :]
            try:
                summary = await self._summarizer.summarize(
                    existing_summary=conversation.summary,
                    messages=older_messages,
                )
            except Exception as exc:
                record_span_exception(span, exc)
                raise
            updated = conversation.model_copy(
                update={"summary": summary, "updated_at": _now()}
            )
            set_span_attributes(
                span,
                {
                    "conversation.message_count": len(messages),
                    "conversation.retained_message_count": len(recent_messages),
                },
            )
            record_conversation_summary_generated()
            logger.info(
                "conversation_summarized",
                extra={
                    "outcome": "success",
                    "message_count": len(recent_messages),
                },
            )
            return updated, recent_messages, True

    def memory_context(
        self,
        *,
        conversation: Conversation,
        messages: list[ConversationMessage],
    ) -> ConversationMemoryContext:
        return ConversationMemoryContext(
            summary=conversation.summary,
            recent_messages=messages[-self._max_recent_messages :],
        )


class ConversationService:
    def __init__(
        self,
        *,
        repository: ConversationRepository,
        memory_manager: MemoryManager,
        ttl_seconds: int,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive.")
        self._repository = repository
        self._memory_manager = memory_manager
        self._ttl = timedelta(seconds=ttl_seconds)

    async def create_conversation(
        self,
        *,
        principal: AuthenticatedPrincipal,
        metadata: dict[str, object] | None = None,
    ) -> Conversation:
        with tracer.start_as_current_span("conversation.create") as span:
            now = _now()
            conversation = Conversation(
                conversation_id=str(uuid4()),
                owner_subject=principal.subject,
                created_at=now,
                updated_at=now,
                expires_at=now + self._ttl,
                metadata=dict(metadata or {}),
            )
            created = await self._repository.create_conversation(conversation)
            active_count = await self._repository.active_conversation_count()
            record_conversation_created(active_count=active_count)
            span.set_attribute("conversation.created", True)
            logger.info("conversation_created", extra={"outcome": "success"})
            return created

    async def load_conversation(
        self,
        conversation_id: str,
        principal: AuthenticatedPrincipal,
    ) -> Conversation:
        with tracer.start_as_current_span("conversation.load") as span:
            conversation = await self._repository.get_conversation(conversation_id)
            if conversation is None:
                span.set_attribute("conversation.found", False)
                raise ConversationNotFoundError("Conversation not found.")
            self._validate_access(conversation, principal)
            span.set_attribute("conversation.found", True)
            return conversation

    async def append_message(
        self,
        *,
        conversation_id: str,
        principal: AuthenticatedPrincipal,
        role: ConversationRole,
        content: str,
    ) -> ConversationMessage:
        with tracer.start_as_current_span("conversation.append") as span:
            conversation = await self.load_conversation(conversation_id, principal)
            self._validate_message_role(role, principal)
            message = ConversationMessage(
                message_id=str(uuid4()),
                conversation_id=conversation_id,
                role=role,
                content=content,
                created_at=_now(),
            )
            appended = await self._repository.append_message(message)
            messages = await self._repository.list_messages(conversation_id)
            updated_conversation = conversation.model_copy(
                update={"updated_at": appended.created_at}
            )
            summarized = False
            retained_messages = messages
            try:
                (
                    updated_conversation,
                    retained_messages,
                    summarized,
                ) = await self._memory_manager.maybe_summarize(
                    conversation=updated_conversation,
                    messages=messages,
                )
            except Exception as exc:
                record_span_exception(span, exc)
                logger.warning(
                    "conversation_summary_failed",
                    extra={
                        "outcome": "error",
                        "message_count": len(messages),
                    },
                )
            await self._repository.update_conversation(updated_conversation)
            if summarized:
                await self._repository.replace_messages(
                    conversation_id,
                    retained_messages,
                )
                messages = retained_messages
            average_length = await self._repository.average_message_count()
            record_conversation_message_added(
                role=role.value,
                message_count=len(messages),
                average_length=average_length,
            )
            set_span_attributes(
                span,
                {
                    "conversation.role": role.value,
                    "conversation.message_count": len(messages),
                    "conversation.summarized": summarized,
                },
            )
            logger.info(
                "conversation_message_added",
                extra={
                    "outcome": "success",
                    "roles": [role.value],
                    "message_count": len(messages),
                },
            )
            return appended

    async def list_messages(
        self,
        *,
        conversation_id: str,
        principal: AuthenticatedPrincipal,
        limit: int,
    ) -> list[ConversationMessage]:
        await self.load_conversation(conversation_id, principal)
        messages = await self._repository.list_messages(conversation_id)
        return messages[-limit:]

    async def delete_conversation(
        self,
        *,
        conversation_id: str,
        principal: AuthenticatedPrincipal,
    ) -> None:
        with tracer.start_as_current_span("conversation.delete") as span:
            conversation = await self.load_conversation(conversation_id, principal)
            self._validate_access(conversation, principal)
            deleted = await self._repository.delete_conversation(conversation_id)
            if not deleted:
                raise ConversationNotFoundError("Conversation not found.")
            active_count = await self._repository.active_conversation_count()
            record_conversation_deleted(active_count=active_count)
            span.set_attribute("conversation.deleted", True)
            logger.info("conversation_deleted", extra={"outcome": "success"})

    async def memory_context(
        self,
        *,
        conversation_id: str,
        principal: AuthenticatedPrincipal,
    ) -> ConversationMemoryContext:
        conversation = await self.load_conversation(conversation_id, principal)
        messages = await self._repository.list_messages(conversation_id)
        return self._memory_manager.memory_context(
            conversation=conversation,
            messages=messages,
        )

    def _validate_access(
        self,
        conversation: Conversation,
        principal: AuthenticatedPrincipal,
    ) -> None:
        if SupportRole.PLATFORM_ADMIN.value in principal.roles:
            return
        if conversation.owner_subject != principal.subject:
            raise ConversationNotFoundError("Conversation not found.")

    def _validate_message_role(
        self,
        role: ConversationRole,
        principal: AuthenticatedPrincipal,
    ) -> None:
        if role != ConversationRole.SYSTEM:
            return
        if SupportRole.PLATFORM_ADMIN.value not in principal.roles:
            raise ConversationAccessDeniedError("System messages require admin access.")


def _now() -> datetime:
    return datetime.now(UTC)


def _snippet(content: str, max_length: int = 120) -> str:
    normalized = " ".join(content.split())
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[: max_length - 3].rstrip()}..."
