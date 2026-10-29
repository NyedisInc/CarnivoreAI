
export type MaybeWindow = (Window & typeof globalThis) | undefined;

export function hostWindow(): MaybeWindow {
    return typeof window !== 'undefined' ? window : undefined;
}

export function hostDocument(): Document | undefined {
    return typeof document !== 'undefined' ? document : undefined;
}
