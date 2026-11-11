
export interface RolloutPreview {
    enabled: boolean;
    direction: 'on' | 'off' | '';
    total: number;
    tethered: number;
    pending: number;
    will_restart: number;
    adopted: number;
    subagents: number;
    background: number;
    excluded: Record<string, number>;
    reasons: Record<string, number>;
}

export interface RolloutRow { tmux_name: string; state: string; reason: string }

export interface RolloutView {
    enabled: boolean;
    state: string;
    direction: string;
    epoch: number;
    reason: string;
    counts: Record<string, number>;
    reasons: Record<string, number>;
    rows: RolloutRow[];
}

const LIVE_STATES = ['running', 'paused'];
const WAITING = ['pending'];

export function showsProgress(view: Pick<RolloutView, 'state'> | null): boolean {
    return view !== null && LIVE_STATES.includes(view.state);
}

export function sortedCounts(counts: Record<string, number>): Array<[string, number]> {
    return Object.entries(counts).filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

export function canRestartNow(row: RolloutRow): boolean {
    return WAITING.includes(row.state);
}

export function movable(preview: Pick<RolloutPreview, 'will_restart'> | null): number {
    return preview?.will_restart ?? 0;
}
