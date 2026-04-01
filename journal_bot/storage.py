from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from .config import AppPaths
from .models import ActiveSession, CompletedEntry


class LocalStorage:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths

    def load_active_sessions(self) -> list[ActiveSession]:
        payload = self._load_json(self.paths.active_sessions_file)
        return [ActiveSession.from_dict(item) for item in payload.get("sessions", [])]

    def save_active_sessions(self, sessions: list[ActiveSession]) -> None:
        self._write_json(
            self.paths.active_sessions_file,
            {"sessions": [session.to_dict() for session in sessions]},
        )

    def save_active_session(self, session: ActiveSession) -> None:
        sessions = self.load_active_sessions()
        remaining = [item for item in sessions if item.session_id != session.session_id]
        remaining.append(session)
        self.save_active_sessions(remaining)

    def delete_active_session(self, session_id: str) -> None:
        sessions = [item for item in self.load_active_sessions() if item.session_id != session_id]
        self.save_active_sessions(sessions)

    def save_completed_entry(self, entry: CompletedEntry) -> None:
        path = self._journal_path(entry.user_id, entry.date_key)
        self._write_json(path, entry.to_dict())

    def load_completed_entries_for_user(self, user_id: int) -> list[CompletedEntry]:
        user_prefix = f"{user_id}_"
        entries: list[CompletedEntry] = []
        for path in sorted(self.paths.journals_dir.glob(f"{user_prefix}*.json")):
            payload = self._load_json(path)
            if payload:
                entries.append(CompletedEntry.from_dict(payload))
        return entries

    def has_completed_entry(self, user_id: int, date_key: str) -> bool:
        return self._journal_path(user_id, date_key).exists()

    def completion_stats(self, user_id: int, start_date: date, end_date: date) -> dict[str, Any]:
        completed_dates = {
            entry.date_key
            for entry in self.load_completed_entries_for_user(user_id)
            if start_date.isoformat() <= entry.date_key <= end_date.isoformat()
        }
        total_days = (end_date - start_date).days + 1
        completed_days = len(completed_dates)
        percentage = (completed_days / total_days * 100) if total_days > 0 else 0.0
        return {
            "total_days": total_days,
            "completed_days": completed_days,
            "percentage": percentage,
            "completed_dates": sorted(completed_dates),
        }

    def _journal_path(self, user_id: int, date_key: str) -> Path:
        return self.paths.journals_dir / f"{user_id}_{date_key}.json"

    def _load_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            return {}
        return payload

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
