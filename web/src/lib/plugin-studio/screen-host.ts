import { openModal } from '../modal';
import type { StudioOpenOptions } from './types';

let openInFlight = false;
let openCancelled = false;
let openGeneration = 0;
let activeModalOpen = false;
let activeClose: (() => void) | null = null;

export function isPluginStudioOpen(): boolean {
    return openInFlight || activeModalOpen;
}

export function closePluginStudio(): boolean {
    if (openInFlight) {
        openCancelled = true;
        openInFlight = false;
        return true;
    }
    if (!activeClose) return false;
    const fn = activeClose;
    activeClose = null;
    fn();
    return true;
}

export async function openPluginStudio(options?: StudioOpenOptions): Promise<boolean> {
    if (openInFlight || activeModalOpen) return false;
    openInFlight = true;
    openCancelled = false;
    const gen = ++openGeneration;
    try {
        const mod = await import('./StudioModal.svelte');
        if (openCancelled || gen !== openGeneration) {
            return false;
        }
        activeModalOpen = true;
        openInFlight = false;
        let closed = false;
        const promise = openModal<null, {
            initialOptions?: StudioOpenOptions;
            onRegisterClose?: (fn: () => void) => void;
        }>(mod.default as never, {
            ...(options ? { initialOptions: options } : {}),
            onRegisterClose: (fn) => {
                if (closed) {
                    fn();
                    return;
                }
                activeClose = () => {
                    if (closed) return;
                    closed = true;
                    fn();
                };
            },
        });
        await promise;
        return true;
    } catch {
        return false;
    } finally {
        if (gen === openGeneration) {
            openInFlight = false;
            openCancelled = false;
            activeModalOpen = false;
            activeClose = null;
        }
    }
}
