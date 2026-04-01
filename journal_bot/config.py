from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .models import UserConfig


@dataclass(slots=True)
class AppPaths:
    root: Path
    config_dir: Path
    data_dir: Path
    runtime_dir: Path
    journals_dir: Path
    settings_file: Path
    prompts_file: Path
    runtime_users_file: Path
    active_sessions_file: Path


@dataclass(slots=True)
class BotSettings:
    command_prefix: str
    default_timezone: str
    allow_runtime_user_setup: bool
    users: list[UserConfig]
    prompts: dict[str, list[str]]
    token: str


class ConfigError(RuntimeError):
    """Raised when the bot configuration is invalid."""


def build_paths(root: Path | None = None) -> AppPaths:
    app_root = root or Path(__file__).resolve().parent.parent
    config_dir = app_root / "config"
    data_dir = app_root / "data"
    runtime_dir = data_dir / "runtime"
    journals_dir = data_dir / "journals"
    return AppPaths(
        root=app_root,
        config_dir=config_dir,
        data_dir=data_dir,
        runtime_dir=runtime_dir,
        journals_dir=journals_dir,
        settings_file=config_dir / "settings.json",
        prompts_file=config_dir / "prompts.json",
        runtime_users_file=runtime_dir / "user_overrides.json",
        active_sessions_file=runtime_dir / "active_sessions.json",
    )


def ensure_data_dirs(paths: AppPaths) -> None:
    paths.runtime_dir.mkdir(parents=True, exist_ok=True)
    paths.journals_dir.mkdir(parents=True, exist_ok=True)


def load_bot_settings(paths: AppPaths) -> BotSettings:
    load_dotenv(paths.root / ".env")
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        raise ConfigError("Missing DISCORD_BOT_TOKEN in .env.")
    settings_payload = _load_json_file(
        paths.settings_file,
        missing_hint="Copy config/settings.example.json to config/settings.json and edit it.",
    )
    prompts_payload = _load_json_file(
        paths.prompts_file,
        missing_hint="Copy config/prompts.example.json to config/prompts.json and edit it.",
    )
    default_timezone = str(settings_payload.get("default_timezone", "America/Phoenix"))
    base_users = [
        UserConfig.from_dict(user_payload, default_timezone)
        for user_payload in settings_payload.get("users", [])
    ]
    overrides = _load_json_if_exists(paths.runtime_users_file).get("users", {})
    merged_users = [_merge_user_override(user, overrides.get(str(user.user_id), {}), default_timezone) for user in base_users]
    extra_runtime_users = [
        UserConfig.from_dict(payload, default_timezone)
        for user_id, payload in overrides.items()
        if int(user_id) not in {user.user_id for user in base_users}
    ]
    merged_users.extend(extra_runtime_users)
    prompts = {
        str(prompt_set): [str(question).strip() for question in questions if str(question).strip()]
        for prompt_set, questions in prompts_payload.items()
    }
    if not prompts:
        raise ConfigError("No prompt sets found in config/prompts.json.")
    for user in merged_users:
        if user.prompt_set not in prompts:
            raise ConfigError(
                f"User {user.user_id} references prompt set '{user.prompt_set}', which does not exist."
            )
    return BotSettings(
        command_prefix=str(settings_payload.get("command_prefix", "!")),
        default_timezone=default_timezone,
        allow_runtime_user_setup=bool(settings_payload.get("allow_runtime_user_setup", True)),
        users=merged_users,
        prompts=prompts,
        token=token,
    )


def save_runtime_user_override(paths: AppPaths, user_config: UserConfig) -> None:
    payload = _load_json_if_exists(paths.runtime_users_file)
    users = payload.setdefault("users", {})
    users[str(user_config.user_id)] = user_config.to_dict()
    _write_json_file(paths.runtime_users_file, payload)


def _merge_user_override(
    base_user: UserConfig,
    override_payload: dict[str, Any],
    default_timezone: str,
) -> UserConfig:
    merged = base_user.to_dict()
    merged.update(override_payload or {})
    merged["user_id"] = base_user.user_id
    return UserConfig.from_dict(merged, default_timezone)


def _load_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return _load_json_file(path)


def _load_json_file(path: Path, missing_hint: str | None = None) -> dict[str, Any]:
    if not path.exists():
        hint = f" {missing_hint}" if missing_hint else ""
        raise ConfigError(f"Missing required file: {path}.{hint}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ConfigError(f"Expected a JSON object in {path}.")
    return payload


def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
