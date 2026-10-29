<script lang="ts">
  import { t } from '../../lib/i18n/index.svelte';

  let { points }: { points: (number | null)[] } = $props();
  const W = 100;
  const H = 24;
  const known = $derived(points.filter((value): value is number => value !== null));
  const path = $derived.by(() => {
    if (known.length === 0) return '';
    const low = Math.min(...known);
    const span = Math.max(...known) - low || 1;
    const step = points.length > 1 ? W / (points.length - 1) : 0;
    let pen = false;
    return points.map((value, at) => {
      if (value === null) { pen = false; return ''; }
      const command = pen ? 'L' : 'M';
      pen = true;
      return `${command}${(at * step).toFixed(2)} ${(H - 2 - (value - low) / span * (H - 4)).toFixed(2)}${command === 'M' ? 'h.01' : ''}`;
    }).join('');
  });
</script>

<svg class="viz-spark" viewBox="0 0 {W} {H}" preserveAspectRatio="none" role="img" aria-label={t('viz.spark_label', { points: known.length })}>
  <path d={path} />
</svg>

<style>
  @layer components {
    .viz-spark { display: block; width: 100%; height: 100%; min-height: var(--oc-space-5); overflow: visible; }

    .viz-spark path { fill: none; stroke: var(--oc-series-1); stroke-width: 1.5; vector-effect: non-scaling-stroke; stroke-linejoin: round; stroke-linecap: round; }
  }
</style>
