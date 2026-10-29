import type { RailPrompt, Tick } from './types';

export interface TickView {
    ordinal: number;
    y: number;
    dim: boolean;
    current: boolean;
    cluster: boolean;
    tip: string;
}

export function tickViews(
    ticks: Tick[],
    prompts: RailPrompt[],
    currentOrdinal: number,
): TickView[] {
    const total = prompts.length;
    const byOrdinal = (ordinal: number): RailPrompt | null =>
        prompts.find((p) => p.ordinal === ordinal) ?? null;
    return ticks.map((tick) => {
        let anyMatch = false;
        let isCurrent = false;
        for (const ordinal of tick.ordinals) {
            const p = byOrdinal(ordinal);
            if (p?.matches) anyMatch = true;
            if (ordinal === currentOrdinal) isCurrent = true;
        }
        return {
            ordinal: tick.ordinals[0] ?? 0,
            y: tick.y,
            dim: !anyMatch,
            current: isCurrent,
            cluster: tick.ordinals.length > 1,
            tip: tipFor(tick, total, byOrdinal),
        };
    });
}

function tipFor(
    tick: Tick,
    total: number,
    byOrdinal: (ordinal: number) => RailPrompt | null,
): string {
    const head = tick.ordinals[0] ?? 0;
    const last = tick.ordinals[tick.ordinals.length - 1] ?? head;
    const range = tick.ordinals.length > 1 ? `#${head}-#${last}` : `#${head}`;
    const sentence = `${range} of ${total}`;
    const first = byOrdinal(head);
    return first?.preview ? `${sentence}  ${first.preview}` : sentence;
}
