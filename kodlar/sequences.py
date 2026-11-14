from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping

from .models import new_id


MAX_GROUP_DEPTH = 5


def _safe_delay(value: Any, default: float = 1.0) -> float:
    try:
        delay = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(delay):
        return default
    return max(0.0, round(delay, 3))


@dataclass(slots=True)
class SequenceItem:
    kind: str
    delay_seconds: float = 1.0
    macro_id: str = ""
    group: SequenceGroup | None = None


@dataclass(slots=True)
class SequenceGroup:
    name: str = "Yeni Grup"
    children: list[SequenceItem] = field(default_factory=list)
    id_token: str = field(default_factory=new_id)


def sequence_group_from_dict(
    data: Mapping[str, Any],
    *,
    depth: int = 0,
) -> SequenceGroup:
    group = SequenceGroup(
        name=str(data.get("name") or "Yeni Grup")[:40],
        id_token=str(data.get("id_token") or new_id()),
    )
    if depth >= MAX_GROUP_DEPTH:
        return group

    raw_children = data.get("children", [])
    if not isinstance(raw_children, list):
        return group

    for raw_item in raw_children:
        if not isinstance(raw_item, Mapping):
            continue
        kind = str(raw_item.get("kind", "macro")).lower()
        delay = _safe_delay(raw_item.get("delay_seconds"), 1.0)
        if kind == "group" and isinstance(raw_item.get("group"), Mapping):
            group.children.append(
                SequenceItem(
                    kind="group",
                    delay_seconds=delay,
                    group=sequence_group_from_dict(raw_item["group"], depth=depth + 1),
                )
            )
        elif kind == "macro":
            macro_id = str(raw_item.get("macro_id", ""))
            if macro_id:
                group.children.append(
                    SequenceItem(
                        kind="macro",
                        delay_seconds=delay,
                        macro_id=macro_id,
                    )
                )
    return group


def sequence_group_to_dict(group: SequenceGroup) -> dict[str, Any]:
    children: list[dict[str, Any]] = []
    for item in group.children:
        if item.kind == "group" and item.group is not None:
            children.append({
                "kind": "group",
                "delay_seconds": item.delay_seconds,
                "group": sequence_group_to_dict(item.group),
            })
        elif item.kind == "macro" and item.macro_id:
            children.append({
                "kind": "macro",
                "delay_seconds": item.delay_seconds,
                "macro_id": item.macro_id,
            })
    return {
        "name": group.name,
        "id_token": group.id_token,
        "children": children,
    }


def sequence_groups_from_list(data: Any) -> list[SequenceGroup]:
    if not isinstance(data, list):
        return []
    return [
        sequence_group_from_dict(item)
        for item in data
        if isinstance(item, Mapping)
    ]


def iter_groups(groups: list[SequenceGroup]):
    for group in groups:
        yield group
        nested = [
            item.group
            for item in group.children
            if item.kind == "group" and item.group is not None
        ]
        yield from iter_groups(nested)


def grouped_macro_ids(groups: list[SequenceGroup]) -> set[str]:
    result: set[str] = set()
    for group in iter_groups(groups):
        result.update(
            item.macro_id
            for item in group.children
            if item.kind == "macro" and item.macro_id
        )
    return result


def group_macro_ids(group: SequenceGroup) -> set[str]:
    return grouped_macro_ids([group])
