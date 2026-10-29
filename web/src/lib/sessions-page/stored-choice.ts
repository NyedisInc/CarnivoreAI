
export function readChoice<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
    try {
        const v = globalThis.localStorage?.getItem(key) ?? '';
        return (allowed as readonly string[]).includes(v) ? (v as T) : fallback;
    } catch {
        return fallback;
    }
}

export function writeChoice(key: string, value: string): void {
    try {
        globalThis.localStorage?.setItem(key, value);
    } catch {
    }
}
