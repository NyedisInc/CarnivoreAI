
import { paceState } from '../../../../../client/js/labels/pace.js';

export type Tone = 'ok' | 'warn' | 'info';

export interface SampleMeter {
    short: string;
    pct: number;
    tone: Tone;
    detail?: string;
    reset?: string;
    at?: string;
    elapsedPct?: number;
    scope: 'session' | 'account';
}

export function sampleScale(tone: Tone): 1 | 3 {
    return tone === 'warn' ? 3 : 1;
}

export function samplePaceState(meter: SampleMeter): 'on' | 'ahead' | 'over' | null {
    return paceState(meter.pct, meter.elapsedPct ?? null);
}

export const SAMPLE_METERS: Readonly<Record<'context' | 'window_5h' | 'window_7d', SampleMeter>> = {
    context: { short: 'ctx', pct: 44, tone: 'info', detail: '438k/1M', scope: 'session' },
    window_5h: { short: '5h', pct: 64, tone: 'warn', reset: '3h 23m', at: 'at 8:58 pm', elapsedPct: 32, scope: 'account' },
    window_7d: { short: '7d', pct: 38, tone: 'ok', reset: '4d 1h', at: 'sat 9:00 am', elapsedPct: 42, scope: 'account' },
};

export const SAMPLE_SESSION = {
    model: 'Opus 5.5',
    effort: 'high',
    tokens: '940k / 41k',
    cost: '$4.82',
    account: 'claude max, joe',
    agents: 2,
    shells: 3,
    timers: 2,
    nextTimer: '4m',
} as const;

export interface SampleTimer {
    rule: string;
    task: string;
    due: string;
}

export interface SampleAgent {
    id: string;
    name: string;
    task: string;
    state: 'work' | 'wait';
    stateName: string;
    elapsed: string;
}

export interface SampleShell {
    id: string;
    cmd: string;
    elapsed: string;
    owner: string | null;
    detail: string;
}

export const SAMPLE_TIMERS: readonly SampleTimer[] = [
    { rule: 'every 5 minutes', task: 'check the deploy', due: 'in 4m 12s' },
    { rule: 'once, after 30m', task: 'summarize new issues', due: 'in 18m 38s' },
];

export const SAMPLE_AGENTS: readonly SampleAgent[] = [
    { id: 'ag1', name: 'general-purpose', task: 'draft the screenshot script', state: 'work', stateName: 'working', elapsed: '5m 05s' },
    { id: 'ag2', name: 'Explore', task: 'map the repo for the foot bar cells', state: 'wait', stateName: 'waiting on you', elapsed: '10m 05s' },
];

export const SAMPLE_SHELLS: readonly SampleShell[] = [
    { id: 'bt00001', cmd: 'grep -rn FootStats web/src', elapsed: '10m 11s', owner: 'ag1', detail: 'pid 61001, 1 process' },
    { id: 'bt00010', cmd: 'npm run build', elapsed: '7m 55s', owner: 'ag2', detail: 'pid 61010, exited' },
    { id: 'bt00022', cmd: 'python3 scripts/testsrv status', elapsed: '1m 45s', owner: null, detail: 'pid 61022, 2 processes' },
];

export function leadingMeter(ids: readonly ('context' | 'window_5h' | 'window_7d')[]): 'context' | 'window_5h' | 'window_7d' | null {
    let best: 'context' | 'window_5h' | 'window_7d' | null = null;
    for (const id of ids) {
        if (best === null || SAMPLE_METERS[id].pct > SAMPLE_METERS[best].pct) best = id;
    }
    return best;
}
