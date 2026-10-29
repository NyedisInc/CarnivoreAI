import * as arrangement from '../drawer/store';

export function pinnedUuidSet(): ReadonlySet<string> {
    const state = arrangement.current();
    const out = new Set<string>();
    for (const name of state.pinned) {
        const uuid = state.ids[name] ?? (name.startsWith('@') ? name.slice(1) : '');
        if (uuid) out.add(uuid);
    }
    return out;
}
