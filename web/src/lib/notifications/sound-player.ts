import { authFetch } from '../../opscenter/api/auth.svelte';
import { SOUNDS } from '../notify-card/contract.gen';

export type Fetcher = typeof authFetch;

export const FRESH_MS = 30000;

export const playable = (sound: string): boolean => (SOUNDS as readonly string[]).includes(sound) && sound !== 'none' && sound !== 'default';

let player: HTMLAudioElement | null = null;

export function playSound(sound: string): void {
    if (!playable(sound)) return;
    try {
        player?.pause();
        player = new Audio(`/static/sounds/carnivore-${sound}.wav`);
        void player.play().catch(() => undefined);
    } catch {
        player = null;
    }
}

interface ToastLike { local?: boolean; notify_type?: unknown; session_name?: unknown; created_at?: unknown }

export async function soundForToast(toast: ToastLike | null | undefined, fetcher: Fetcher = authFetch): Promise<void> {
    if (!toast || toast.local === true || typeof toast.notify_type !== 'string' || !toast.notify_type) return;
    const made = typeof toast.created_at === 'string' ? Date.parse(toast.created_at) : NaN;
    if (Number.isFinite(made) && Date.now() - made > FRESH_MS) return;
    const query = new URLSearchParams({ type_id: toast.notify_type });
    if (typeof toast.session_name === 'string' && toast.session_name) query.set('name', toast.session_name);
    try {
        const body = await fetcher<{ sound?: string } | null>(`/notifications/play?${query}`);
        const sound = body?.sound === 'default' ? 'soft' : body?.sound ?? '';
        playSound(sound);
    } catch {
    }
}

export function installNotifySound(): void {
    (globalThis as { NotifySound?: unknown }).NotifySound = { forToast: soundForToast, play: playSound };
}
