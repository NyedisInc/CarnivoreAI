
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from src.core import ui_preferences, ui_preferences_store

PRIMARY = 'terminal:@primary'


def parent_key(parent: Any) -> str:
    epoch = parent.session.tmux_created_epoch
    return parent.tmux_session if epoch is None else f'{parent.tmux_session}:{epoch}'


def child_tab(child: Any) -> str:
    row = child.session_row_id
    return f'terminal:row:{row}' if isinstance(row, int) else f'terminal:{child.session.id}'


def add_to_arrangement(value: dict | None, parent: Any, child: Any) -> dict:
    source = value or {'v': 1, 'sessions': {}}
    sessions = dict(source.get('sessions') or {})
    key = parent_key(parent)
    entry = dict(sessions.pop(key, {'layout': None, 'groups': {}}))
    groups = dict(entry.get('groups') or {})
    parent_tab = (f'terminal:row:{parent.session_row_id}'
                  if isinstance(parent.session_row_id, int) else f'terminal:{parent.session.id}')
    slot = next((slot for slot, group in groups.items()
                 if parent_tab in (group.get('tabs') or [])), PRIMARY)
    group = dict(groups.get(slot) or {'tabs': [slot]})
    tabs = list(group.get('tabs') or [slot])
    tab = child_tab(child)
    if not any(tab in (one.get('tabs') or []) for one in groups.values()):
        tabs.append(tab)
    if len(tabs) > ui_preferences.MAX_TABS_PER_GROUP:
        raise ValueError('the parent tab strip is full')
    group['tabs'] = tabs
    groups[slot] = group
    entry['groups'] = groups
    sessions[key] = entry
    while len(sessions) > ui_preferences.MAX_TERMINAL_LAYOUTS:
        sessions.pop(next(iter(sessions)))
    return {'v': 1, 'sessions': sessions}


async def persist(app: Any, parent: Any, child: Any) -> str:
    from src.api.preferences_routes import broadcast_changed

    pref = getattr(app.state, 'ui_preferences_store', None)
    if pref is None:
        return 'unavailable'
    for _ in range(3):
        block = await asyncio.to_thread(pref.read)
        try:
            value = add_to_arrangement(block['values'].get('terminal_layouts'), parent, child)
        except ValueError:
            return 'tab_strip_full'
        result = await asyncio.to_thread(pref.update, {'terminal_layouts': value}, block['revision'])
        if result.status == ui_preferences_store.STALE_REVISION:
            continue
        if result.status == ui_preferences_store.COMMITTED:
            await broadcast_changed(SimpleNamespace(app=app), result, None)
            return 'saved'
        return result.status
    return 'conflict'
