import * as Store from './store';

export function isPinnedRow(row: Record<string, unknown>): boolean {
    const name = typeof row.name === 'string' ? row.name : '';
    if (name && Store.isPinned(name)) return true;
    const uuid = typeof row.session_uuid === 'string' ? row.session_uuid : '';
    if (!uuid) return false;
    const { pinned, ids } = Store.current();
    return pinned.some((pinnedName) => ids[pinnedName] === uuid);
}
