
interface AsleepRecord {
    asleep?: boolean;
    archived_at?: unknown;
    tmux_name?: string;
    title?: string | null;
    session_uuid?: string;
    unread?: boolean;
    owned?: boolean;
    tmux_created_epoch?: number;
    agent_family?: string | null;
    agent_family_source?: string | null;
    project_id?: number | null;
    project_name?: string | null;
    working_dir?: string | null;
    notifications_muted?: boolean;
    pinned_theme?: string | null;
    next_wake_at?: number | null;
    automations_state?: string | null;
    automations_total?: number | null;
    automations_enabled?: number | null;
    automations_next?: unknown[] | null;
    host_key?: string | null;
    host_label?: string | null;
}

export function addRows(
    rows: Array<Record<string, unknown>>,
    records: readonly unknown[],
    keep?: ReadonlySet<string>,
): number {
    const taken = new Set((rows || []).map((r) => r && r.name));
    let added = 0;
    const list = Array.isArray(records) ? records.slice() : [];
    if (keep && keep.size) {
        const kept = (x: unknown): number => keep.has((x as AsleepRecord | null)?.session_uuid || '') ? 0 : 1;
        list.sort((a, b) => kept(a) - kept(b));
    }
    for (const raw of list) {
        const rec = raw as AsleepRecord | null;
        if (!rec || rec.asleep !== true || rec.archived_at || !rec.tmux_name) continue;
        if (taken.has(rec.tmux_name)) continue;
        taken.add(rec.tmux_name);
        rows.push({
            name: rec.tmux_name,
            label: rec.title != null ? rec.title : null,
            asleep: true,
            status: 'asleep',
            session_uuid: rec.session_uuid,
            session_id: null,
            is_active: false,
            unread: rec.unread === true,
            created_by_cloude: typeof rec.owned === 'boolean' ? rec.owned : null,
            created_at_epoch: Number(rec.tmux_created_epoch) || 0,
            agent_family: rec.agent_family != null ? rec.agent_family : null,
            agent_family_source: rec.agent_family_source != null ? rec.agent_family_source : null,
            project_id: rec.project_id != null ? rec.project_id : null,
            project_name: rec.project_name != null ? rec.project_name : null,
            working_dir: rec.working_dir != null ? rec.working_dir : null,
            notifications_muted: !!rec.notifications_muted,
            pinned_theme: rec.pinned_theme || null,
            next_wake_at: typeof rec.next_wake_at === 'number' && rec.next_wake_at > 0 ? rec.next_wake_at : null,
            automations_state: rec.automations_state ?? null,
            automations_total: rec.automations_total ?? null,
            automations_enabled: rec.automations_enabled ?? null,
            automations_next: rec.automations_next ?? null,
            host_key: rec.host_key ?? 'local',
            host_label: rec.host_label ?? 'this machine',
            host_state: 'up',
        });
        added += 1;
    }
    return added;
}
