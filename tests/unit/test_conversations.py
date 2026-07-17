import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from app.core.auth import AuthenticatedPrincipal
from app.repositories.conversations import InMemoryConversationRepository
from app.schemas.conversations import (
    Conversation,
    ConversationMessage,
    ConversationRole,
)
from app.services.conversations import (
    ConversationAccessDeniedError,
    ConversationNotFoundError,
    ConversationService,
    ConversationSummarizer,
    MemoryManager,
    MockConversationSummarizer,
)


@pytest.mark.anyio
async def test_in_memory_repository_stores_messages_in_order() -> None:
    repository = InMemoryConversationRepository()
    conversation = _conversation()
    await repository.create_conversation(conversation)
    later = _message("2", created_at=conversation.created_at + timedelta(seconds=2))
    earlier = _message("1", created_at=conversation.created_at + timedelta(seconds=1))

    await repository.append_message(later)
    await repository.append_message(earlier)

    messages = await repository.list_messages(conversation.conversation_id)
    assert [message.message_id for message in messages] == ["1", "2"]


@pytest.mark.anyio
async def test_repository_delete_removes_messages() -> None:
    repository = InMemoryConversationRepository()
    conversation = _conversation()
    await repository.create_conversation(conversation)
    await repository.append_message(_message("1", created_at=conversation.created_at))

    deleted = await repository.delete_conversation(conversation.conversation_id)

    assert deleted
    assert await repository.list_messages(conversation.conversation_id) == []


@pytest.mark.anyio
async def test_repository_average_message_count() -> None:
    repository = InMemoryConversationRepository()
    first = _conversation()
    second = first.model_copy(update={"conversation_id": "conversation-2"})
    await repository.create_conversation(first)
    await repository.create_conversation(second)
    await repository.append_message(_message("1", created_at=first.created_at))
    await repository.append_message(_message("2", created_at=first.created_at))

    assert await repository.average_message_count() == 1.0


@pytest.mark.anyio
async def test_repository_replace_messages_requires_conversation() -> None:
    repository = InMemoryConversationRepository()

    with pytest.raises(KeyError):
        await repository.replace_messages("missing", [])


@pytest.mark.anyio
async def test_repository_removes_expired_conversations() -> None:
    repository = InMemoryConversationRepository()
    conversation = _conversation(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    await repository.create_conversation(conversation)

    assert await repository.get_conversation(conversation.conversation_id) is None
    assert await repository.active_conversation_count() == 0


@pytest.mark.anyio
async def test_conversation_service_lifecycle() -> None:
    service = _service()
    principal = _principal()

    conversation = await service.create_conversation(principal=principal)
    loaded = await service.load_conversation(conversation.conversation_id, principal)
    message = await service.append_message(
        conversation_id=conversation.conversation_id,
        principal=principal,
        role=ConversationRole.USER,
        content="Need help with billing.",
    )
    messages = await service.list_messages(
        conversation_id=conversation.conversation_id,
        principal=principal,
        limit=50,
    )
    await service.delete_conversation(
        conversation_id=conversation.conversation_id,
        principal=principal,
    )

    assert loaded.conversation_id == conversation.conversation_id
    assert message.content == "Need help with billing."
    assert len(messages) == 1
    with pytest.raises(ConversationNotFoundError):
        await service.load_conversation(conversation.conversation_id, principal)


@pytest.mark.anyio
async def test_append_message_to_missing_conversation_raises_not_found() -> None:
    service = _service()

    with pytest.raises(ConversationNotFoundError):
        await service.append_message(
            conversation_id="missing",
            principal=_principal(),
            role=ConversationRole.USER,
            content="hello",
        )


@pytest.mark.anyio
async def test_delete_missing_conversation_raises_not_found() -> None:
    service = _service()

    with pytest.raises(ConversationNotFoundError):
        await service.delete_conversation(
            conversation_id="missing",
            principal=_principal(),
        )


@pytest.mark.anyio
async def test_conversation_service_enforces_ownership() -> None:
    service = _service()
    conversation = await service.create_conversation(principal=_principal("owner"))

    with pytest.raises(ConversationNotFoundError):
        await service.load_conversation(
            conversation.conversation_id, _principal("other")
        )


@pytest.mark.anyio
async def test_platform_admin_can_access_any_conversation() -> None:
    service = _service()
    conversation = await service.create_conversation(principal=_principal("owner"))

    loaded = await service.load_conversation(
        conversation.conversation_id,
        _principal("admin", roles=frozenset({"platform_admin"})),
    )

    assert loaded.conversation_id == conversation.conversation_id


@pytest.mark.anyio
async def test_support_manager_does_not_receive_admin_override() -> None:
    service = _service()
    conversation = await service.create_conversation(principal=_principal("owner"))

    with pytest.raises(ConversationNotFoundError):
        await service.load_conversation(
            conversation.conversation_id,
            _principal("manager", roles=frozenset({"support_manager"})),
        )


@pytest.mark.anyio
async def test_system_message_requires_platform_admin() -> None:
    service = _service()
    principal = _principal()
    conversation = await service.create_conversation(principal=principal)

    with pytest.raises(ConversationAccessDeniedError):
        await service.append_message(
            conversation_id=conversation.conversation_id,
            principal=principal,
            role=ConversationRole.SYSTEM,
            content="System-only note.",
        )


@pytest.mark.anyio
async def test_service_treats_expired_conversation_as_missing() -> None:
    service = _service(ttl_seconds=1)
    principal = _principal()
    conversation = await service.create_conversation(principal=principal)
    expired = conversation.model_copy(
        update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
    )
    await service._repository.update_conversation(expired)  # noqa: SLF001

    with pytest.raises(ConversationNotFoundError):
        await service.load_conversation(conversation.conversation_id, principal)


@pytest.mark.anyio
async def test_memory_manager_summarizes_and_retains_recent_messages() -> None:
    service = _service(summary_threshold=3, max_recent_messages=2)
    principal = _principal()
    conversation = await service.create_conversation(principal=principal)

    for index in range(4):
        await service.append_message(
            conversation_id=conversation.conversation_id,
            principal=principal,
            role=ConversationRole.USER,
            content=f"message {index}",
        )

    loaded = await service.load_conversation(conversation.conversation_id, principal)
    messages = await service.list_messages(
        conversation_id=conversation.conversation_id,
        principal=principal,
        limit=50,
    )

    assert loaded.summary is not None
    assert "Summarized" in loaded.summary
    assert len(messages) == 2
    assert [message.content for message in messages] == ["message 2", "message 3"]


@pytest.mark.anyio
async def test_summary_merges_previous_summary() -> None:
    service = _service(summary_threshold=3, max_recent_messages=2)
    principal = _principal()
    conversation = await service.create_conversation(principal=principal)
    await service._repository.update_conversation(  # noqa: SLF001
        conversation.model_copy(update={"summary": "Prior summary."})
    )

    for index in range(4):
        await service.append_message(
            conversation_id=conversation.conversation_id,
            principal=principal,
            role=ConversationRole.USER,
            content=f"message {index}",
        )

    loaded = await service.load_conversation(conversation.conversation_id, principal)

    assert loaded.summary is not None
    assert loaded.summary.startswith("Prior summary.")


@pytest.mark.anyio
async def test_summarization_failure_preserves_messages() -> None:
    service = _service(
        summary_threshold=3,
        max_recent_messages=2,
        summarizer=FailingSummarizer(),
    )
    principal = _principal()
    conversation = await service.create_conversation(principal=principal)

    for index in range(4):
        await service.append_message(
            conversation_id=conversation.conversation_id,
            principal=principal,
            role=ConversationRole.USER,
            content=f"message {index}",
        )

    loaded = await service.load_conversation(conversation.conversation_id, principal)
    messages = await service.list_messages(
        conversation_id=conversation.conversation_id,
        principal=principal,
        limit=50,
    )

    assert loaded.summary is None
    assert [message.content for message in messages] == [
        "message 0",
        "message 1",
        "message 2",
        "message 3",
    ]


@pytest.mark.anyio
async def test_concurrent_appends_preserve_all_messages() -> None:
    service = _service(summary_threshold=20, max_recent_messages=5)
    principal = _principal()
    conversation = await service.create_conversation(principal=principal)

    await asyncio.gather(
        *(
            service.append_message(
                conversation_id=conversation.conversation_id,
                principal=principal,
                role=ConversationRole.USER,
                content=f"message {index}",
            )
            for index in range(10)
        )
    )

    messages = await service.list_messages(
        conversation_id=conversation.conversation_id,
        principal=principal,
        limit=50,
    )

    assert len(messages) == 10
    assert {message.content for message in messages} == {
        f"message {index}" for index in range(10)
    }


@pytest.mark.anyio
async def test_memory_context_returns_summary_and_recent_messages() -> None:
    service = _service(max_recent_messages=1)
    principal = _principal()
    conversation = await service.create_conversation(principal=principal)
    await service.append_message(
        conversation_id=conversation.conversation_id,
        principal=principal,
        role=ConversationRole.USER,
        content="first",
    )
    await service.append_message(
        conversation_id=conversation.conversation_id,
        principal=principal,
        role=ConversationRole.ASSISTANT,
        content="second",
    )

    context = await service.memory_context(
        conversation_id=conversation.conversation_id,
        principal=principal,
    )

    assert len(context.recent_messages) == 1
    assert context.recent_messages[0].content == "second"


def test_memory_manager_rejects_invalid_threshold() -> None:
    with pytest.raises(ValueError):
        MemoryManager(
            summarizer=MockConversationSummarizer(),
            summary_threshold=0,
            max_recent_messages=1,
        )


def test_memory_manager_rejects_invalid_recent_message_limit() -> None:
    with pytest.raises(ValueError):
        MemoryManager(
            summarizer=MockConversationSummarizer(),
            summary_threshold=1,
            max_recent_messages=0,
        )


def test_memory_manager_requires_threshold_above_recent_message_limit() -> None:
    with pytest.raises(ValueError):
        MemoryManager(
            summarizer=MockConversationSummarizer(),
            summary_threshold=3,
            max_recent_messages=3,
        )


def test_conversation_service_rejects_invalid_ttl() -> None:
    with pytest.raises(ValueError):
        _service(ttl_seconds=0)


def _service(
    *,
    ttl_seconds: int = 3600,
    summary_threshold: int = 10,
    max_recent_messages: int = 4,
    summarizer: ConversationSummarizer | None = None,
) -> ConversationService:
    return ConversationService(
        repository=InMemoryConversationRepository(),
        memory_manager=MemoryManager(
            summarizer=summarizer or MockConversationSummarizer(),
            summary_threshold=summary_threshold,
            max_recent_messages=max_recent_messages,
        ),
        ttl_seconds=ttl_seconds,
    )


def _principal(
    subject: str = "agent-123",
    roles: frozenset[str] = frozenset({"support_agent"}),
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        subject=subject,
        email=None,
        roles=roles,
        provider="mock",
    )


def _conversation(
    *,
    expires_at: datetime | None = None,
) -> Conversation:
    now = datetime.now(UTC)
    return Conversation(
        conversation_id="conversation-1",
        owner_subject="agent-123",
        created_at=now,
        updated_at=now,
        expires_at=expires_at or now + timedelta(hours=1),
        metadata={},
    )


def _message(message_id: str, *, created_at: datetime) -> ConversationMessage:
    return ConversationMessage(
        message_id=message_id,
        conversation_id="conversation-1",
        role=ConversationRole.USER,
        content=f"content {message_id}",
        created_at=created_at,
    )


class FailingSummarizer:
    async def summarize(
        self,
        *,
        existing_summary: str | None,
        messages: Sequence[ConversationMessage],
    ) -> str:
        raise RuntimeError("summary unavailable")
