from __future__ import annotations

from .models import ActiveSession


def format_prompt_preview(questions: list[str]) -> str:
    lines = [f"{index}. {question}" for index, question in enumerate(questions, start=1)]
    return "\n".join(lines)


def format_compiled_entry(session: ActiveSession) -> str:
    lines = [
        f"## Journal Entry for {session.date_key}",
        "",
    ]
    for index, question in enumerate(session.questions):
        answer = session.answer_for(index)
        if not answer:
            continue
        lines.append(f"**{index + 1}. {question}**")
        lines.append(answer)
        lines.append("")
    if len(lines) == 2:
        lines.extend(
            [
                "_No answers were recorded before the session was marked complete._",
                "",
            ]
        )
    return "\n".join(lines).strip()
