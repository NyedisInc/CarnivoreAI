
export interface ModelName {
    readonly name: string;
    readonly provider: string;
}

export function modelName(id: string | null): ModelName {
    const clean = (id ?? '').replace(/^~/, '');
    const cut = clean.lastIndexOf('/');
    return cut < 0 ? { name: clean, provider: '' } : { name: clean.slice(cut + 1), provider: clean.slice(0, cut).replace(/^~/, '') };
}

export function compact(n: number): string {
    if (n < 1000) return String(n);
    const [value, unit] = n < 1_000_000 ? [n / 1000, 'k'] : [n / 1_000_000, 'm'];
    return `${value >= 100 ? Math.round(value) : Math.round(value * 10) / 10}${unit}`;
}

export function tokensText(input: number | null, output: number | null, inWord: string, outWord: string): string {
    return input === null && output === null ? '-' : `${compact(input ?? 0)} ${inWord} / ${compact(output ?? 0)} ${outWord}`;
}

export function costText(usd: number | null): string {
    return usd === null ? '-' : `$${usd.toFixed(usd < 0.1 ? 4 : 2)}`;
}

export function latencyText(ms: number | null): string {
    return ms === null ? '-' : `${(ms / 1000).toFixed(1)}s`;
}

export function firstLine(text: string | null): string {
    return (text ?? '').split('\n').find((line) => line.trim() !== '')?.trim() ?? '';
}

export function dayKey(ts: number): string {
    const d = new Date(ts * 1000);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export function dayLabel(ts: number, todayWord: string, yesterdayWord: string, now: Date = new Date()): string {
    const key = dayKey(ts);
    const today = dayKey(now.getTime() / 1000);
    const yesterday = dayKey(now.getTime() / 1000 - 86400);
    if (key === today) return todayWord;
    if (key === yesterday) return yesterdayWord;
    return new Date(ts * 1000).toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' });
}

export function percent(part: number, whole: number): string {
    return whole ? `${Math.round((part / whole) * 100)}%` : '0%';
}
