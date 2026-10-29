
<script lang="ts">
    import { onMount } from 'svelte';
    import type { Translate } from '../sessions/types';
    import * as Ansi from './engine/ansi';
    import * as Art from './engine/art';

    interface Props {
        files: number;
        t: Translate;
    }

    const { files, t }: Props = $props();

    let host = $state<HTMLElement | null>(null);
    let live: { redraw: () => void; destroy: () => void } | null = null;

    function grid(c: number): Ansi.Grid {
        const g = Ansi.blank(c, 5);
        const lab = t('warez.elite.strip.title');
        Art.overlay(g, 0, 3, Art.drip(c, { seed: 5, len: 1 }));
        Ansi.put(g, 2, 1, lab, 14, 0);
        for (let x = 2 + lab.length + 2; x < c - 2; x++) Ansi.put(g, x, 1, '░▒▓▒'.charAt(x % 4), x % 8 < 4 ? 1 : 8, 0);
        const tx = ` ${t('warez.elite.strip.files', { n: files })} `;
        if (c > 60) Ansi.put(g, c - tx.length - 2, 0, tx, 7, 0);
        return g;
    }

    onMount(() => {
        if (!host) return;
        live = Art.live(host, grid);
        return () => live?.destroy();
    });
    $effect(() => {
        void files;
        live?.redraw();
    });
</script>

<h2 class="sr">{t('warez.elite.aria.strip')}</h2>
<div class="m1-strip" bind:this={host}></div>
