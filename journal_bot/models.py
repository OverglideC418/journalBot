from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class UserConfig:
    user_id: int
    guild_id: int | None
    channel_id: int | None
    schedule_time: str
    timezone: str
    prompt_set: str
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any], default_timezone: str) -> "UserConfig":
        return cls(
            user_id=int(data["user_id"]),
            guild_id=int(data["guild_id"]) if data.get("guild_id") is not None else None,
            channel_id=int(data["channel_id"]) if data.get("channel_id") is not None else None,
            schedule_time=str(data.get("schedule_time", "21:00")),
            timezone=str(data.get("timezone") or default_timezone),
            prompt_set=str(data.get("prompt_set", "default")),
            enabled=bool(data.get("enabled", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ActiveSession:
    session_id: str
    user_id: int
    guild_id: int | None
    channel_id: int
    date_key: str
    timezone: str
    prompt_set: str
    questions: list[str]
    question_message_ids: list[int]
    started_at: str
    answers: dict[str, str] = field(default_factory=dict)

    def answer_for(self, index: int) -> str | None:
        return self.answers.get(str(index))

    def set_answer(self, index: int, value: str) -> None:
        self.answers[str(index)] = value

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ActiveSession":
        return cls(
            session_id=str(data["session_id"]),
            user_id=int(data["user_id"]),
            guild_id=int(data["guild_id"]) if data.get("guild_id") is not None else None,
            channel_id=int(data["channel_id"]),
            date_key=str(data["date_key"]),
            timezone=str(data["timezone"]),
            prompt_set=str(data["prompt_set"]),
            questions=list(data["questions"]),
            question_message_ids=[int(value) for value in data["question_message_ids"]],
            started_at=str(data["started_at"]),
            answers={str(key): str(value) for key, value in data.get("answers", {}).items()},
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CompletedEntry:
    session_id: str
    user_id: int
    guild_id: int | None
    channel_id: int
    date_key: str
    timezone: str
    prompt_set: str
    started_at: str
    completed_at: str
    questions: list[str]
    answers: dict[str, str]
    compiled_message_id: int | None = None

    @classmethod
    def from_session(
        cls,
        session: ActiveSession,
        completed_at: datetime,
        compiled_message_id: int | None,
    ) -> "CompletedEntry":
        return cls(
            session_id=session.session_id,
            user_id=session.user_id,
            guild_id=session.guild_id,
            channel_id=session.channel_id,
            date_key=session.date_key,
            timezone=session.timezone,
            prompt_set=session.prompt_set,
            started_at=session.started_at,
            completed_at=completed_at.isoformat(),
            questions=session.questions,
            answers=dict(session.answers),
            compiled_message_id=compiled_message_id,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CompletedEntry":
        return cls(
            session_id=str(data["session_id"]),
            user_id=int(data["user_id"]),
            guild_id=int(data["guild_id"]) if data.get("guild_id") is not None else None,
            channel_id=int(data["channel_id"]),
            date_key=str(data["date_key"]),
            timezone=str(data["timezone"]),
            prompt_set=str(data["prompt_set"]),
            started_at=str(data["started_at"]),
            completed_at=str(data["completed_at"]),
            questions=list(data["questions"]),
            answers={str(key): str(value) for key, value in data.get("answers", {}).items()},
            compiled_message_id=(
                int(data["compiled_message_id"]) if data.get("compiled_message_id") is not None else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
