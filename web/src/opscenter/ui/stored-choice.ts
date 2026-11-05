
export function isOneOf<T extends string>(value: string, allowed: readonly T[]): value is T {
    return (allowed as readonly string[]).includes(value);
}

export function readChoice<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
    try {
        const v = globalThis.localStorage?.getItem(key) ?? '';
        return isOneOf(v, allowed) ? v : fallback;
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
