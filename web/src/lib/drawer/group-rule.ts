import { isListedSession, type BucketRow } from './bucketing';

export const RULE_FLAGS = ['running', 'sleeping', 'coffee', 'sharing', 'pinned', 'remote', 'swarm', 'unread', 'waiting'] as const;
export type RuleFlag = (typeof RULE_FLAGS)[number];

export interface GroupRule {
    flags: RuleFlag[];
    prefix: string;
    suffix: string;
}

export interface RuleContext {
    keptAwake(name: string): boolean;
    isPinned(name: string): boolean;
    isSwarm(row: Record<string, unknown>): boolean;
}

export const EMPTY_CONTEXT: RuleContext = { keptAwake: () => false, isPinned: () => false, isSwarm: () => false };

export function ruleOf(raw: unknown): GroupRule | null {
    if (!raw || typeof raw !== 'object') return null;
    const r = raw as { flags?: unknown; prefix?: unknown; suffix?: unknown };
    const flags = RULE_FLAGS.filter((f) => Array.isArray(r.flags) && (r.flags as unknown[]).includes(f));
    const prefix = typeof r.prefix === 'string' ? r.prefix : '';
    const suffix = typeof r.suffix === 'string' ? r.suffix : '';
    return flags.length || prefix || suffix ? { flags, prefix, suffix } : null;
}

function has(flag: RuleFlag, row: Record<string, unknown>, ctx: RuleContext): boolean {
    const name = String(row.name ?? '');
    switch (flag) {
        case 'running': return row.asleep !== true && row.closed !== true && row.status !== 'dead';
        case 'sleeping': return row.asleep === true;
        case 'coffee': return ctx.keptAwake(name);
        case 'sharing': return row.spectator_expires_at != null && row.spectator_expires_at !== '';
        case 'pinned': return ctx.isPinned(name) || row.is_pinned === true;
        case 'remote': return typeof row.host_key === 'string' && row.host_key !== '' && row.host_key !== 'local';
        case 'swarm': return ctx.isSwarm(row);
        case 'unread': return row.unread === true;
        case 'waiting': return row.status === 'question';
    }
}

export function matches(rule: GroupRule, row: Record<string, unknown>, ctx: RuleContext = EMPTY_CONTEXT): boolean {
    if (!isListedSession(row as BucketRow)) return false;
    const shown = String(row.label || row.name || '').toLowerCase();
    if (rule.prefix && !shown.startsWith(rule.prefix.toLowerCase())) return false;
    if (rule.suffix && !shown.endsWith(rule.suffix.toLowerCase())) return false;
    return rule.flags.every((f) => has(f, row, ctx));
}
