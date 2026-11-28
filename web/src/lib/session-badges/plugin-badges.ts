import { isSafeDisplayText, MAX_LABEL, MAX_TEXT } from '../cplug-ui/validate';
import { resolveActiveSlots, runSlotDescriptorAction } from '../plugins/slot-actions';
import type { BadgeItem } from './slot';

function isPlainObject(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function rowSessionRefs(row: Record<string, unknown>): { refs: Set<string>; primary: string | null } {
    const refs = new Set<string>();
    const nested = isPlainObject(row.session) ? row.session : null;
    const candidates = [
        row.session_uuid,
        row.session_id,
        nested?.id,
        nested?.session_uuid,
        row.tmux_session,
        row.name,
    ];
    let primary: string | null = null;
    for (const cand of candidates) {
        if (typeof cand === 'string' && cand.trim()) {
            const val = cand.trim();
            refs.add(val);
            if (!primary) primary = val;
        }
    }
    return { refs, primary };
}

function targetRefsFrom(obj: unknown): string[] {
    if (!isPlainObject(obj)) return [];
    const out: string[] = [];
    for (const key of ['session_ref', 'session_id', 'session_uuid'] as const) {
        const val = obj[key];
        if (typeof val === 'string' && val.trim()) {
            out.push(val.trim());
        } else if (Array.isArray(val)) {
            for (const item of val) {
                if (typeof item === 'string' && item.trim()) out.push(item.trim());
            }
        }
    }
    return out;
}

function matchesSessionScope(item: Record<string, unknown>, rowRefs: ReadonlySet<string>): boolean {
    const targets = [
        ...targetRefsFrom(item.when),
        ...targetRefsFrom(item.data),
        ...targetRefsFrom(item.props),
    ];
    if (targets.length === 0) return true;
    return targets.some((target) => rowRefs.has(target));
}

function mapBadgeTone(raw: unknown): string | undefined {
    if (typeof raw !== 'string') return undefined;
    switch (raw) {
        case 'danger':
        case 'bad':
            return 'bad';
        case 'warn':
            return 'warn';
        case 'accent':
            return 'accent';
        case 'good':
            return 'good';
        case 'info':
            return 'info';
        case 'stripe':
            return 'stripe';
        case 'muted':
            return 'muted';
        default:
            return undefined;
    }
}

export function pluginBadges(row: Record<string, unknown>): BadgeItem[] {
    const { refs, primary } = rowSessionRefs(row);
    const out: BadgeItem[] = [];

    for (const valid of resolveActiveSlots('session.badges')) {
        if (valid.kind !== 'descriptor') continue;
        const raw = valid.entry.item;
        if (!matchesSessionScope(raw, refs)) continue;

        const textCandidate = valid.badge ?? valid.label ?? valid.title ?? valid.id;
        if (!textCandidate || !isSafeDisplayText(textCandidate, MAX_LABEL)) continue;
        const titleCandidate = valid.tooltip ?? valid.title ?? valid.label ?? textCandidate;
        if (!isSafeDisplayText(titleCandidate, MAX_TEXT)) continue;

        const tone = mapBadgeTone(raw.tone ?? valid.tone);
        const pct =
            isPlainObject(raw.data) && typeof raw.data.pct === 'number' && Number.isFinite(raw.data.pct)
                ? raw.data.pct
                : undefined;

        const item: BadgeItem = {
            kind: 'plugin',
            key: `${valid.entry.plugin_id}:${valid.id}:${out.length}`,
            text: textCandidate,
            title: titleCandidate,
            ...(tone ? { tone } : {}),
            ...(pct !== undefined ? { pct } : {}),
            ...(valid.action && !valid.disabled
                ? {
                      activate: () => {
                          void runSlotDescriptorAction(valid.entry.plugin_id, valid.action!, {
                              sessionRef: primary,
                              confirm: valid.confirm,
                              title: valid.label || textCandidate,
                              tone: valid.tone,
                          }).catch((err: unknown) =>
                              console.error('[session-badges] plugin badge action failed', valid.entry.plugin_id, valid.id, err),
                          );
                      },
                  }
                : {}),
        };
        out.push(item);
    }

    return out;
}
