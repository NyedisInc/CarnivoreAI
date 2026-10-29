
<script lang="ts">
    import { onDestroy, tick, untrack } from 'svelte';
    import type { Translate } from '../sessions/types';
    import { barRuns, cellsOf, menuFrame, titleSegs } from './header-paint';
    import type { MenuPanel } from './menu-model';

    interface Props {
        panels: MenuPanel[];
        onPick: (panelId: string, key: string) => void;
        t: Translate;
    }

    const { panels, onPick, t }: Props = $props();

    let nav = $state<HTMLElement | null>(null);
    let layer = $state<HTMLElement | null>(null);
    let cells = $state<number[]>([]);
    let fill = $state<Record<string, number>>({});
    let timer: ReturnType<typeof setInterval> | null = null;
    const reduced = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;

    const targets = $derived.by(() => {
        const m: Record<string, number> = {};
        for (const p of panels) for (const it of p.items) if (it.frac != null) m[`${p.id}:${it.key}`] = Math.round(Math.max(0, Math.min(1, it.frac)) * 10);
        return m;
    });

    $effect(() => {
        const to = targets;
        untrack(() => {
            if (timer) clearInterval(timer);
            timer = null;
            if (reduced) {
                fill = { ...to };
                return;
            }
            timer = setInterval(() => {
                let moving = false;
                const next = { ...fill };
                for (const key of Object.keys(to)) {
                    const cur = next[key] ?? 0;
                    if (cur !== to[key]) {
                        next[key] = cur + (cur < (to[key] ?? 0) ? 1 : -1);
                        moving = true;
                    }
                }
                fill = next;
                if (!moving && timer) {
                    clearInterval(timer);
                    timer = null;
                }
            }, 26);
        });
    });
    onDestroy(() => { if (timer) clearInterval(timer); });

    export function repaint(swaps: (() => void)[] = []): void {
        if (!nav || !layer) {
            swaps.forEach((swap) => swap());
            return;
        }
        const next = Array.from(nav.querySelectorAll<HTMLElement>('.hd-panel')).map(cellsOf);
        if (next.length !== cells.length || next.some((n, i) => n !== cells[i])) cells = next;
        void tick().then(() => {
            if (!nav || !layer) {
                swaps.forEach((swap) => swap());
                return;
            }
            const bars = Array.from(nav.querySelectorAll<HTMLElement>('.hd-bar'));
            bars.forEach((bar) => { bar.hidden = false; });
            const drop = bars.map((bar) => {
                const pn = bar.closest('.hd-panel') as HTMLElement;
                const pc = getComputedStyle(pn);
                return bar.getBoundingClientRect().right > pn.getBoundingClientRect().right - parseFloat(pc.paddingRight) + 1;
            });
            bars.forEach((bar, i) => { bar.hidden = drop[i]!; });
            swaps.push(menuFrame(nav, layer));
            swaps.forEach((swap) => swap());
        });
    }
</script>

<nav class="hd-panels" aria-label={t('warez.elite.aria.board')} bind:this={nav}>
    <div class="m1h-pf" aria-hidden="true" bind:this={layer}></div>
    {#each panels as p, pi (p.id)}
        <section class="hd-panel" data-panel={p.id} aria-label={p.title.toLowerCase()}>
            <h2 class="hd-pt">
                <span class="sr">{p.title}</span>
                <span class="hd-gt" aria-hidden="true">{#each titleSegs(p.title, cells[pi] ?? 0) as s}<i style:color={`var(--bbs-g${s.k})`}>{s.c}</i>{/each}</span>
            </h2>
            <ul class="hd-pl">
                {#each p.items as it (it.key)}
                    {@const [on, off] = barRuns(fill[`${p.id}:${it.key}`] ?? 0)}
                    <li>
                        <button type="button" class="hd-it" data-key={it.key} aria-pressed={p.on === it.key} aria-keyshortcuts={it.key} onclick={() => onPick(p.id, it.key)}>
                            <span class="hd-ar" aria-hidden="true">▸</span><span class="hd-k"><b class="hd-br">[</b>{it.key}<b class="hd-br">]</b></span>
                            <span class="hd-l">{it.label}</span>{#if it.count != null}{' '}<span class="hd-c">({it.count})</span>{/if}{#if it.frac != null}<span class="hd-bar" aria-hidden="true">{#if on}<b>{'▓'.repeat(on)}</b>{/if}{'░'.repeat(off)}</span>{/if}
                        </button>
                    </li>
                {/each}
            </ul>
        </section>
    {/each}
</nav>
