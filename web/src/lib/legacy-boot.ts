/* event that starts */

/* and the real */
export const APP_BOOT_COMPLETE = 'app-boot-complete';

interface BootLatch {
    EVENT?: string;
    isComplete?: () => boolean;
}

export function whenLegacyBootComplete(
    target: Window | null,
    work: () => void,
): () => void {
    if (!target) return () => {};
    const latch = (target as unknown as { AppBootComplete?: BootLatch }).AppBootComplete;
    if (!latch || latch.isComplete?.() === true) {
        work();
        return () => {};
    }
    let done = false;
    const onAnnounced = (): void => {
        if (done) return;
        done = true;
        target.removeEventListener(latch.EVENT ?? APP_BOOT_COMPLETE, onAnnounced);
        work();
    };
    target.addEventListener(latch.EVENT ?? APP_BOOT_COMPLETE, onAnnounced);
    return () => {
        if (done) return;
        done = true;
        target.removeEventListener(latch.EVENT ?? APP_BOOT_COMPLETE, onAnnounced);
    };
}
