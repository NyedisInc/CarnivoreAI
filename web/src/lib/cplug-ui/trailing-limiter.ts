
export interface TrailingLimiter {
    hit: (run: () => void) => void;
    cancel: () => void;
}

export function createTrailingLimiter(max: number, windowMs: number, now: () => number = () => Date.now()): TrailingLimiter {
    let sent: number[] = [];
    let timer: ReturnType<typeof setTimeout> | null = null;
    const recent = (): number[] => (sent = sent.filter((at) => now() - at < windowMs));
    const fire = (run: () => void): void => {
        timer = null;
        recent().push(now());
        run();
    };
    return {
        hit(run: () => void): void {
            if (timer !== null) return;
            if (recent().length < max) return fire(run);
            timer = setTimeout(() => fire(run), Math.max(0, (sent[0] ?? 0) + windowMs - now()));
        },
        cancel(): void {
            if (timer !== null) clearTimeout(timer);
            timer = null;
        },
    };
}
