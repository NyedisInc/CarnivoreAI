
<script lang="ts">
    import type { Snippet } from 'svelte';
    import * as Ansi from './engine/ansi';

    interface Props {
        title: string;
        tag?: string;
        info?: string;
        active?: boolean;
        label: string;
        cls?: string;
        live?: string;
        el?: HTMLElement | null;
        children: Snippet;
    }

    let { title, tag = '', info = '', active = false, label, cls = '', live = '', el = $bindable(null), children }: Props = $props();

    interface Frame {
        title: string;
        tag: string;
        info: string;
    }

    function topGrid(cols: number, hot: boolean, f: Frame): Ansi.Grid {
        const g = Ansi.blank(cols, 1);
        const run = hot ? 4 : 8;
        const plate = hot ? 15 : 7;
        for (let x = 0; x < cols; x++) Ansi.put(g, x, 0, '▒░▓▒'.charAt(x % 4), run, 0);
        Ansi.put(g, 0, 0, '\\\\', hot ? 10 : 8, 0);
        Ansi.put(g, cols - 2, 0, '//', hot ? 10 : 8, 0);
        const t = ` ${f.title} `;
        Ansi.put(g, 3, 0, '▓▒░', run, 0);
        Ansi.put(g, 6, 0, t, plate, 0);
        if (f.tag && cols > t.length + f.tag.length + 14) Ansi.put(g, cols - f.tag.length - 5, 0, f.tag, hot ? 7 : 8, 0);
        return g;
    }
    function botGrid(cols: number, hot: boolean, f: Frame): Ansi.Grid {
        const g = Ansi.blank(cols, 1);
        const run = hot ? 4 : 8;
        for (let x = 0; x < cols; x++) Ansi.put(g, x, 0, '▒░▓▒'.charAt((x + 2) % 4), run, 0);
        Ansi.put(g, 0, 0, '//', hot ? 10 : 8, 0);
        Ansi.put(g, cols - 2, 0, '\\\\', hot ? 10 : 8, 0);
        const t = ` ${f.info} `;
        if (f.info && t.length < cols - 8) Ansi.put(g, 4, 0, t, hot ? 15 : 7, 0);
        return g;
    }

    const column = '▓\n'.repeat(159);

    function frame(node: HTMLElement, f: Frame): { update: (f: Frame) => void; destroy: () => void } {
        let cur = f;
        let last = 0;
        const draw = (): void => {
            const cols = Math.max(12, Math.floor(node.clientWidth / 8));
            last = cols;
            const paint = (sel: string, make: (hot: boolean) => Ansi.Grid): void => {
                (['d', 'h'] as const).forEach((k) => {
                    const host = node.querySelector<HTMLElement>(`${sel} .pf-${k}`);
                    if (!host) return;
                    const a = Ansi.el(make(k === 'h'));
                    a.style.position = 'relative';
                    a.style.width = 'auto';
                    host.replaceChildren(a);
                });
            };
            paint('.pf-t', (hot) => topGrid(cols, hot, cur));
            paint('.pf-b', (hot) => botGrid(cols, hot, cur));
        };
        draw();
        const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => { if (Math.floor(node.clientWidth / 8) !== last) draw(); }) : null;
        ro?.observe(node);
        return {
            update: (next) => {
                cur = next;
                draw();
            },
            destroy: () => ro?.disconnect(),
        };
    }
</script>

<section class={`pane ${cls}`} data-active={active ? 'true' : 'false'} aria-label={label} bind:this={el} use:frame={{ title, tag, info }}>
    <div class="pf pf-t" aria-hidden="true"><div class="pf-d"></div><div class="pf-h"></div></div>
    <div class="pf pf-l" aria-hidden="true"><i class="pf-d">{column}</i><i class="pf-h">{column}</i></div>
    <div class="pf pf-r" aria-hidden="true"><i class="pf-d">{column}</i><i class="pf-h">{column}</i></div>
    <div class="pf pf-b" aria-hidden="true"><div class="pf-d"></div><div class="pf-h"></div></div>
    <div class="pane-in">{@render children()}</div>
    <div class="sr" role="status" aria-live="polite">{live}</div>
</section>
