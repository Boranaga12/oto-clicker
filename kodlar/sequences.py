from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping

from .models import new_id
import random


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
    gap_seconds: float | None = None
    gap_random_seconds: float = 0.0


@dataclass(slots=True)
class WritingBlock:
    opening: str
    closing: str = ""
    id_token: str = field(default_factory=new_id)


@dataclass(slots=True)
class SequenceGroup:
    name: str = "Yeni Grup"
    children: list[SequenceItem] = field(default_factory=list)
    id_token: str = field(default_factory=new_id)
    writing_blocks: list[WritingBlock] = field(default_factory=list)
    enabled: bool = True


def sequence_group_from_dict(
    data: Mapping[str, Any],
    *,
    depth: int = 0,
) -> SequenceGroup:
    group = SequenceGroup(
        name=str(data.get("name") or "Yeni Grup")[:40],
        enabled=bool(data.get("enabled", True)),
        id_token=str(data.get("id_token") or new_id()),
    )
    raw_blocks = data.get("writing_blocks", [])
    if isinstance(raw_blocks, list):
        group.writing_blocks = [WritingBlock(str(b.get("opening", "")), str(b.get("closing", "")),
                                            str(b.get("id_token") or new_id()))
                                for b in raw_blocks if isinstance(b, Mapping)]
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
                        gap_seconds=_safe_delay(raw_item['gap_seconds'], 0) if raw_item.get('gap_seconds') is not None else None,
                        gap_random_seconds=_safe_delay(raw_item.get('gap_random_seconds'), 0),
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
            if item.gap_seconds is not None:
                children[-1].update(gap_seconds=item.gap_seconds, gap_random_seconds=item.gap_random_seconds)
    return {
        "name": group.name,
        "enabled": group.enabled,
        "id_token": group.id_token,
        "children": children,
        "writing_blocks": [{"opening": b.opening, "closing": b.closing, "id_token": b.id_token} for b in group.writing_blocks],
    }


def sequence_groups_from_list(data: Any) -> list[SequenceGroup]:
    if not isinstance(data, list):
        return []
    return flatten_groups([
        sequence_group_from_dict(item)
        for item in data
        if isinstance(item, Mapping)
    ])


def migrate_group_timing(groups, configs):
    """Preserve old numeric timing once; subsequent waits belong to transitions."""
    configs = {config.id_token: config for config in configs}
    for group in iter_groups(groups):
        for item in group.children:
            config = configs.get(item.macro_id)
            if config is not None and item.gap_seconds is None:
                item.gap_seconds = config.interval_seconds
                item.gap_random_seconds = config.random_seconds


def transition_delay(item):
    return max(0.0, item.gap_seconds or 0.0)+random.uniform(0.0, max(0.0, item.gap_random_seconds))


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


def flatten_groups(groups: list[SequenceGroup]) -> list[SequenceGroup]:
    """Migrate legacy nested groups in order and assign each macro to one group."""
    seen_macros: set[str] = set()
    seen_groups: set[str] = set()
    for group in groups:
        if group.id_token in seen_groups:
            group.id_token = new_id()
        seen_groups.add(group.id_token)
        flat = []
        stack = list(reversed(group.children))
        visited_groups = {id(group)}
        while stack:
            item = stack.pop()
            if item.kind == 'group' and item.group is not None:
                if id(item.group) not in visited_groups:
                    visited_groups.add(id(item.group))
                    stack.extend(reversed(item.group.children))
            elif item.kind == 'macro' and item.macro_id and item.macro_id not in seen_macros:
                seen_macros.add(item.macro_id)
                item.delay_seconds = 0
                flat.append(item)
        group.children = flat
    return groups


def writing_layout(group: SequenceGroup):
    """Return member roles and errors without repairing unsafe/deleted boundaries."""
    ids = [item.macro_id for item in group.children]
    roles = {}
    errors = []
    for block in group.writing_blocks:
        if block.opening not in ids or block.closing not in ids:
            errors.append("Yazı açılışını ve kapanışını seç.")
            if block.opening in ids:
                roles[block.opening] = ("open", block)
            if block.closing in ids:
                roles[block.closing] = ("close", block)
            continue
        a, b = ids.index(block.opening), ids.index(block.closing)
        if a >= b or any(key in roles for key in ids[a:b+1]):
            errors.append("Yazı bölümleri çakışamaz; açılış kapanıştan önce olmalı.")
            continue
        for i in range(a, b+1):
            roles[ids[i]] = ("open" if i == a else "close" if i == b else "body", block)
    return roles, errors


def transfer_macro(configs, groups, macro_id, destination, target):
    """Move a card between containers without breaking complete chat sections."""
    config = next((c for c in configs if c.id_token == macro_id), None)
    source = next((g for g in groups if any(i.macro_id == macro_id for i in g.children)), None)
    if config is None or (source is not None and not source.enabled) or (destination is not None and not destination.enabled):
        return False
    if destination is source and source is not None:
        return move_group_item(source, macro_id, target)
    moving = [SequenceItem('macro', macro_id=macro_id, gap_seconds=config.interval_seconds,
                           gap_random_seconds=config.random_seconds)]
    blocks = []
    if source is not None:
        roles, errors = writing_layout(source)
        if errors:
            return False
        role, block = roles.get(macro_id, (None, None))
        if role in ('body', 'close') or (role == 'open' and destination is None):
            return False
        start = next(i for i, item in enumerate(source.children) if item.macro_id == macro_id)
        end = start+1
        if role == 'open':
            end = next(i for i, item in enumerate(source.children) if item.macro_id == block.closing)+1
            blocks = [block]
        moving = source.children[start:end]
    if destination is not None:
        roles, errors = writing_layout(destination)
        if errors:
            return False
        target = max(0, min(len(destination.children), target))
        if blocks and target < len(destination.children):
            role = roles.get(destination.children[target].macro_id, (None, None))[0]
            if role in ('body', 'close'):
                return False
    else:
        roots = [c for c in configs if not any(c.id_token == i.macro_id for g in groups for i in g.children)]
        remaining = [c for c in roots if c is not config]
        target = max(0, min(len(roots), target))
        if source is None and roots.index(config) < target:
            target -= 1
        target = min(len(remaining), target)
        if source is None and roots.index(config) == target:
            return False
        configs.remove(config)
        index = configs.index(remaining[target]) if target < len(remaining) else len(configs)
        configs.insert(index, config)
    if source is not None:
        source.children[:] = [item for item in source.children if item not in moving]
        source.writing_blocks[:] = [block for block in source.writing_blocks if block not in blocks]
    if destination is not None:
        destination.children[target:target] = moving
        destination.writing_blocks.extend(blocks)
    return True


def move_group_item(group: SequenceGroup, macro_id: str, target: int) -> bool:
    """Opening handle moves a complete block; closing stays attached."""
    roles, errors = writing_layout(group)
    ids = [item.macro_id for item in group.children]
    if macro_id not in ids or errors:
        return False
    start = ids.index(macro_id)
    end = start + 1
    role, block = roles.get(macro_id, (None, None))
    if role == "close":
        return False
    if role == "open":
        end = ids.index(block.closing) + 1
    target = max(0, min(len(ids), target))
    if start <= target <= end:
        return False
    # Never split another complete block with a block, or place a body at its boundaries.
    for other in group.writing_blocks:
        if other is block and role == "open":
            continue
        a, b = ids.index(other.opening), ids.index(other.closing)
        if role == "open" and a < target <= b:
            return False
    saved = list(group.children)
    moving = group.children[start:end]
    del group.children[start:end]
    if target > start:
        target -= end-start
    group.children[target:target] = moving
    if writing_layout(group)[1]:
        group.children[:] = saved
        return False
    return True
