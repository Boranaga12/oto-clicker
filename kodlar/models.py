from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Any, Mapping
from uuid import uuid4


LEFT_MOUSE_NAMES = {"sol klik", "left click", "sol tık"}
MIN_LEFT_CLICK_INTERVAL = 0.050


def clamp_click_interval(key: str, value: float) -> float:
    if key.strip().lower() in LEFT_MOUSE_NAMES:
        return _as_float(value, 1.0, MIN_LEFT_CLICK_INTERVAL)
    return value


def new_id() -> str:
    return uuid4().hex


def _as_float(value: Any, default: float, minimum: float = 0.0) -> float:
    try:
        parsed = float(value)
        if not math.isfinite(parsed):
            return default
        return max(minimum, parsed)
    except (TypeError, ValueError, OverflowError):
        return default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


@dataclass(slots=True)
class KeyConfig:
    key: str
    interval_seconds: float
    random_seconds: float
    enabled: bool = True
    screen_mode: bool = False
    pixel_x: int = 0
    pixel_y: int = 0
    target_color: str = ""
    pixel_screen_bounds: tuple[int, int, int, int] | None = None
    invert_color: bool = False
    click_x: int = -1
    click_y: int = -1
    id_token: str = field(default_factory=new_id)
    action_chain: bool = False
    actions: list[dict[str, Any]] = field(default_factory=list)
    tab_refresh_seconds: float = 4.0

    def __post_init__(self) -> None:
        self.interval_seconds = clamp_click_interval(self.key, self.interval_seconds)
        self.tab_refresh_seconds = _as_float(self.tab_refresh_seconds, 4.0, .1)

    @property
    def has_click_target(self) -> bool:
        return self.click_x >= 0 and self.click_y >= 0

    @property
    def has_pixel_target(self) -> bool:
        return bool(self.target_color)


def key_config_from_dict(item: Mapping[str, Any]) -> KeyConfig:
    actions = item.get("actions", [])
    if not isinstance(actions, list):
        actions = []

    # Eski tek-eylem profil biçimini yeni liste biçimine geçir.
    if not actions and item.get("chain_type", "Yok") != "Yok":
        action_type = str(item.get("chain_type", "Aktif Et"))
        if action_type == "Diğerlerini Sustur":
            action_type = "Sustur"
        actions = [{
            "type": action_type,
            "target_id": str(item.get("chain_target_id", "")),
            "use_color_change": False,
            "mute_duration": _as_float(item.get("chain_mute_duration"), 1.0),
        }]

    clean_actions = [
        {
            "type": str(action.get("type", "Aktif Et")),
            "target_id": str(action.get("target_id", "")),
            "use_color_change": bool(action.get("use_color_change", False)),
            "mute_duration": _as_float(action.get("mute_duration"), 1.0),
        }
        for action in actions
        if isinstance(action, Mapping)
    ]

    bounds = item.get("pixel_screen_bounds")
    if isinstance(bounds, (list, tuple)) and len(bounds) == 4 and all(type(value) is int for value in bounds) and bounds[2] > 0 and bounds[3] > 0:
        bounds = tuple(bounds)
    else:
        bounds = None

    return KeyConfig(
        key=str(item.get("key", "sol klik")),
        interval_seconds=_as_float(item.get("interval_seconds"), 1.0, 0.001),
        random_seconds=_as_float(item.get("random_seconds"), 0.0),
        enabled=bool(item.get("enabled", True)),
        screen_mode=bool(item.get("screen_mode", False)),
        pixel_x=_as_int(item.get("pixel_x"), 0),
        pixel_y=_as_int(item.get("pixel_y"), 0),
        target_color=str(item.get("target_color", "")),
        pixel_screen_bounds=bounds,
        invert_color=False,  # Legacy flag: monitoring always reacts to a different color.
        click_x=_as_int(item.get("click_x"), -1),
        click_y=_as_int(item.get("click_y"), -1),
        id_token=str(item.get("id_token") or new_id()),
        action_chain=bool(item.get("action_chain", False)),
        actions=clean_actions,
        tab_refresh_seconds=_as_float(item.get('tab_refresh_seconds'), 4.0, .1),
    )


def key_config_to_dict(config: KeyConfig) -> dict[str, Any]:
    data = asdict(config)
    data["interval_seconds"] = clamp_click_interval(config.key, config.interval_seconds)
    return data
