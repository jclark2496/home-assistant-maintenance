from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
from typing import Any
from urllib.parse import urlparse

from .core import DigestConfig


class ConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class AppConfig:
    base_url: str
    token: str
    digest: DigestConfig
    state_path: Path
    remindctl_path: Path
    http_timeout: float = 30.0
    reminder_timeout: float = 30.0


def default_config_dir() -> Path:
    override = os.environ.get("HOME_ASSISTANT_MAINTENANCE_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "home-assistant-maintenance"


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigurationError(f"{label} is missing; run 'ha-maintenance configure'") from exc
    except (OSError, ValueError) as exc:
        raise ConfigurationError(f"{label} is unreadable or invalid JSON") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"{label} must contain a JSON object")
    return value


def _require_private_file(path: Path, label: str) -> None:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError as exc:
        raise ConfigurationError(f"cannot inspect {label}") from exc
    if mode & 0o077:
        raise ConfigurationError(f"{label} permissions must be 0600 (currently {mode:04o})")


def load_config(config_dir: Path | None = None) -> AppConfig:
    directory = config_dir or default_config_dir()
    config_path = directory / "config.json"
    credentials_path = directory / "credentials.json"
    raw = _read_object(config_path, "config file")
    credentials = _read_object(credentials_path, "credentials file")
    _require_private_file(credentials_path, "credentials file")

    token = credentials.get("home_assistant_token")
    if not isinstance(token, str) or not token.strip():
        raise ConfigurationError("credentials file has no home_assistant_token")
    base_url = str(raw.get("home_assistant_url", "")).rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigurationError("home_assistant_url must be an http(s) URL")

    try:
        digest = DigestConfig(
            reminder_list=str(raw.get("reminder_list", "")),
            low_battery_threshold=float(raw.get("low_battery_threshold", 25)),
            special_battery_thresholds={str(k): float(v) for k, v in dict(raw.get("special_battery_thresholds", {})).items()},
            special_battery_names={str(k): str(v) for k, v in dict(raw.get("special_battery_names", {})).items()},
            ignored_battery_entities=frozenset(map(str, raw.get("ignored_battery_entities", []))),
            ignored_update_entities=frozenset(map(str, raw.get("ignored_update_entities", []))),
            max_updates_in_title=int(raw.get("max_updates_in_title", 6)),
            max_batteries_in_title=int(raw.get("max_batteries_in_title", 8)),
            max_title_length=int(raw.get("max_title_length", 900)),
            title_prefix=str(raw.get("title_prefix", "Review Home Assistant")),
        )
        state_path = Path(str(raw.get("state_path", directory / "state.json"))).expanduser()
        remindctl_path = Path(str(raw.get("remindctl_path", "/opt/homebrew/bin/remindctl"))).expanduser()
        return AppConfig(
            base_url=base_url,
            token=token,
            digest=digest,
            state_path=state_path,
            remindctl_path=remindctl_path,
            http_timeout=float(raw.get("http_timeout", 30)),
            reminder_timeout=float(raw.get("reminder_timeout", 30)),
        )
    except (TypeError, ValueError) as exc:
        raise ConfigurationError("config file contains an invalid value") from exc


def write_configuration(*, directory: Path, base_url: str, reminder_list: str, token: str) -> None:
    if not token.strip():
        raise ConfigurationError("token must not be empty")
    parsed = urlparse(base_url.rstrip("/"))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigurationError("Home Assistant URL must be an http(s) URL")
    if not reminder_list.strip():
        raise ConfigurationError("reminder list must not be empty")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    config_path = directory / "config.json"
    credentials_path = directory / "credentials.json"
    config = {
        "home_assistant_url": base_url.rstrip("/"),
        "reminder_list": reminder_list,
        "low_battery_threshold": 25,
        "special_battery_thresholds": {},
        "special_battery_names": {},
        "ignored_battery_entities": [],
        "ignored_update_entities": [],
        "max_updates_in_title": 6,
        "max_batteries_in_title": 8,
        "max_title_length": 900,
        "title_prefix": "Review Home Assistant",
        "state_path": str(directory / "state.json"),
        "remindctl_path": "/opt/homebrew/bin/remindctl",
        "http_timeout": 30,
        "reminder_timeout": 30,
    }
    _atomic_private_json(config_path, config)
    _atomic_private_json(credentials_path, {"home_assistant_token": token})


def _atomic_private_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
