
export function pageHidden(): boolean {
    return typeof document !== 'undefined' && document.visibilityState === 'hidden';
}

export function createKeepAwake(): { hold(): void; drop(): void } {
    let wanted = false;
    let asking = false;
    let sentinel: WakeLockSentinel | null = null;

    async function take(): Promise<void> {
        if (!wanted || sentinel || asking || typeof navigator === 'undefined' || !navigator.wakeLock) return;
        asking = true;
        try {
            const got = await navigator.wakeLock.request('screen');
            if (!wanted) { void got.release(); return; }
            sentinel = got;
            got.addEventListener('release', () => { if (sentinel === got) sentinel = null; });
        } catch (err) {
            if (!(err instanceof DOMException)) throw err;
            console.debug('screen wake lock refused', err.name);
        } finally { asking = false; }
    }

    if (typeof document !== 'undefined') {
        document.addEventListener('visibilitychange', () => { if (!pageHidden()) void take(); });
    }
    return {
        hold(): void { wanted = true; void take(); },
        drop(): void {
            wanted = false;
            const held = sentinel;
            sentinel = null;
            if (held) void held.release();
        },
    };
}
