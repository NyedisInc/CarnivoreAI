
export type OpenPhase = 'opening' | 'opened' | 'failed';

export interface OpenStatus {
    phase: OpenPhase;
    reason: string;
}

const statuses = $state<Record<string, OpenStatus>>({});

export function openStatusKey(
    sessionUuid: string | null | undefined,
    title?: string | null,
): string {
    return String(sessionUuid || '').trim() || String(title || '').trim();
}

export const recentOpenStatus = {
    of(key: string): OpenStatus | undefined {
        return key ? statuses[key] : undefined;
    },
    set(key: string, status: OpenStatus): void {
        if (key) statuses[key] = status;
    },
    reset(): void {
        for (const key of Object.keys(statuses)) delete statuses[key];
    },
};
