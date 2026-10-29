import { bag, call, jsonPost, num, text } from './api';
import type { Limits, RuleKind, Rules } from './types';

export function parseLimits(body: unknown): Limits {
    const row = bag(body);
    return {
        per_day: num(row.per_day),
        used_today: num(row.used_today),
        new_account: row.new_account === true,
        new_account_per_day: num(row.new_account_per_day),
        new_account_days: num(row.new_account_days),
        open_max: num(row.open_max),
        open_now: num(row.open_now),
        cooldown_until: text(row.cooldown_until, 40),
        strikes: num(row.strikes),
        strikes_max: num(row.strikes_max),
        appeals_max: num(row.appeals_max),
        media_per_day: num(row.media_per_day),
        media_used_today: num(row.media_used_today),
    };
}

export function parseRules(body: unknown): Rules {
    const row = bag(body);
    const kinds: RuleKind[] = (Array.isArray(row.kinds) ? row.kinds : []).slice(0, 20).map((k) => {
        const kind = bag(k);
        return { kind: text(kind.kind, 20), open: kind.open === true };
    }).filter((k) => k.kind !== '');
    const caps: Record<string, number> = {};
    for (const [name, value] of Object.entries(bag(row.caps)).slice(0, 40)) {
        const n = num(value);
        if (n !== null) caps[text(name, 40)] = n;
    }
    return { kinds, caps };
}

export async function fetchLimits(): Promise<Limits> {
    return parseLimits(await call<unknown>('/catalog/submissions/limits'));
}

export async function fetchRules(): Promise<Rules> {
    return parseRules(await call<unknown>('/catalog/publish/rules'));
}

export async function postAppeal(id: string, appealText: string): Promise<void> {
    await call<unknown>(`/catalog/submissions/${encodeURIComponent(id)}/appeal`, jsonPost({ text: appealText }));
}

export async function postWithdraw(id: string): Promise<void> {
    await call<unknown>(`/catalog/submissions/${encodeURIComponent(id)}/withdraw`, jsonPost({}));
}
