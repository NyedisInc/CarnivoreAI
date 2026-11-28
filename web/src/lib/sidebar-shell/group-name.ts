
export type GroupNameRefusal = 'empty' | 'duplicate';

export type GroupNameVerdict = { ok: true; value: string } | { ok: false; reason: GroupNameRefusal };

export function judgeGroupName(raw: string, existing: readonly string[]): GroupNameVerdict {
    const value = raw.split(/\s+/).filter(Boolean).join(' ');
    if (value === '') return { ok: false, reason: 'empty' };
    const key = value.toLowerCase();
    if (existing.some((name) => name.trim().toLowerCase() === key)) return { ok: false, reason: 'duplicate' };
    return { ok: true, value };
}
