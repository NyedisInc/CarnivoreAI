
<script lang="ts">
    import { useRender } from './context';
    import type { UiNode } from './validate';

    const { node }: { node: Extract<UiNode, { type: 'sparkline' }> } = $props();
    const ctx = useRender();

    const points = $derived.by(() => {
        const vals = node.values.filter((v) => typeof v === 'number' && Number.isFinite(v));
        if (vals.length === 0) return '';
        if (vals.length === 1) return '2.00,14.00 118.00,14.00';
        const min = Math.min(...vals);
        const max = Math.max(...vals);
        const span = max - min;
        const useHalf = !Number.isFinite(span);
        const halfMin = min / 2;
        const halfMax = max / 2;
        const halfSpan = halfMax - halfMin;
        return vals
            .map((v, idx) => {
                const x = 2 + (idx / (vals.length - 1)) * 116;
                let norm: number;
                if (!useHalf) {
                    norm = span === 0 ? 0.5 : (v - min) / span;
                } else {
                    norm = !Number.isFinite(halfSpan) || halfSpan === 0 ? 0.5 : (v / 2 - halfMin) / halfSpan;
                }
                const y = span === 0 ? 14 : 25 - norm * 22;
                return `${x.toFixed(2)},${y.toFixed(2)}`;
            })
            .join(' ');
    });
</script>

<div class="cu-sparkline" data-cu="sparkline" data-tone={node.tone ?? 'normal'}>
    {#if node.label}<span class="cu-sparkline__label">{node.label}</span>{/if}
    <svg
        class="cu-sparkline__svg"
        viewBox="0 0 120 28"
        preserveAspectRatio="none"
        role="img"
        aria-label={node.label ?? ctx.t('cplug_ui.sparkline_label')}
    >
        {#if points}
            <polyline class="cu-sparkline__line" fill="none" {points} />
        {/if}
    </svg>
</div>
