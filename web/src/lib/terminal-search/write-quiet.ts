/* the newest match */
import type { TermLike } from './types';

export const QUIET_MS = 400;
export const QUIET_MAX_MS = 3000;

export function whenWritesQuiet(
    term: TermLike | null,
    work: () => void,
    quietMs: number = QUIET_MS,
    maxMs: number = QUIET_MAX_MS,
): () => void {
    let done = false;
    let quiet: ReturnType<typeof setTimeout> | null = null;
    let sub: { dispose?(): void } | undefined;
    const finish = (run: boolean): void => {
        if (done) return;
        done = true;
        if (quiet !== null) clearTimeout(quiet);
        clearTimeout(cap);
        sub?.dispose?.();
        if (run) work();
    };
    const arm = (): void => {
        if (quiet !== null) clearTimeout(quiet);
        quiet = setTimeout(() => finish(true), quietMs);
    };
    const cap = setTimeout(() => finish(true), maxMs);
    if (term && typeof term.onWriteParsed === 'function') {
        sub = term.onWriteParsed(arm);
    }
    arm();
    return () => finish(false);
}
