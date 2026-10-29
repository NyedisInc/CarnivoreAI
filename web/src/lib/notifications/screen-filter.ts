import { authFetch } from '../../opscenter/api/auth.svelte';
import { resourcePush } from '../resource-push/boot';
import { deviceKey } from './mute/device-key';

export type Fetcher = typeof authFetch;

interface TypeRow {
    readonly id: string;
    readonly label_key?: string;
}

export interface MutesBody {
    readonly everywhere?: readonly string[];
    readonly here?: readonly string[];
}

export interface NotifyScreenGlobal {
    shows(toast: { notify_type?: unknown } | null | undefined): boolean;
}

export const SCREEN_POLL_MS = 15000;

export class ScreenFilter {
    private known = new Set<string>();
    private labels = new Map<string, string>();
    private ticks: Record<string, boolean> | null = null;
    private muted = new Set<string>();
    private registryLoaded = false;

    constructor(private readonly fetcher: Fetcher = authFetch) {}

    shows(toast: { notify_type?: unknown } | null | undefined): boolean {
        const type = toast?.notify_type;
        if (typeof type !== 'string' || !type) return true;
        if (this.muted.has(type)) return false;
        if (!this.registryLoaded || !this.ticks) return true;
        if (!this.known.has(type)) return true;
        return this.ticks[type] !== false;
    }

    isKnown(type: unknown): type is string {
        return typeof type === 'string' && this.known.has(type);
    }

    labelKey(type: string): string | null {
        return this.labels.get(type) ?? null;
    }

    applyMutes(body: MutesBody | null | undefined): void {
        this.muted = new Set([...(body?.everywhere ?? []), ...(body?.here ?? [])]);
    }

    async refresh(): Promise<void> {
        try {
            if (!this.registryLoaded) {
                const body = await this.fetcher<{ types?: TypeRow[] } | null>('/notifications/types');
                const rows = Array.isArray(body?.types) ? body.types : [];
                this.known = new Set(rows.map((r) => r.id));
                this.labels = new Map(rows.filter((r) => typeof r.label_key === 'string').map((r) => [r.id, r.label_key as string]));
                this.registryLoaded = rows.length > 0;
            }
            const settings = await this.fetcher<{ screen?: Record<string, { value?: unknown }> } | null>('/notifications/settings');
            const next: Record<string, boolean> = {};
            for (const [id, cell] of Object.entries(settings?.screen ?? {})) next[id] = cell?.value !== false;
            this.ticks = next;
        } catch {
            this.ticks = null;
        }
        try {
            const device = deviceKey();
            const query = device ? `?device=${encodeURIComponent(device)}` : '';
            this.applyMutes(await this.fetcher<MutesBody | null>(`/notifications/mutes${query}`));
        } catch {
            this.muted = new Set();
        }
        this.pruneShownCards();
    }

    private pruneShownCards(): void {
        const manager = (globalThis as unknown as { ToastManager?: { pruneHidden?: (shows: ScreenFilter['shows']) => void } }).ToastManager;
        manager?.pruneHidden?.((toast) => this.shows(toast));
    }
}

let installed: ScreenFilter | null = null;

export function currentScreenFilter(): ScreenFilter | null {
    return installed;
}

export function installNotifyScreen(fetcher?: Fetcher): ScreenFilter {
    if (installed) return installed;
    const filter = new ScreenFilter(fetcher);
    installed = filter;
    const host = globalThis as unknown as { NotifyScreen?: NotifyScreenGlobal };
    host.NotifyScreen = { shows: (toast) => filter.shows(toast) };
    resourcePush().pushOrPoll(() => void filter.refresh(), SCREEN_POLL_MS, ['notification_settings']);
    void filter.refresh();
    return filter;
}

export function resetNotifyScreenForTests(): void {
    installed = null;
    delete (globalThis as unknown as { NotifyScreen?: unknown }).NotifyScreen;
}
