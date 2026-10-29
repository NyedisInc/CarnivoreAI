<script lang="ts">
  import SegmentedMeterBar from '../../lib/ui/SegmentedMeterBar.svelte';
  import type { Snippet } from 'svelte';
  import type { HTMLAttributes } from 'svelte/elements';

  interface Props extends Omit<HTMLAttributes<HTMLSpanElement>, 'class'> {
    variant?: 'segments' | 'fill';
    pct?: number | null;
    segments?: number;
    filled?: number;
    scale: number | null;
    paceElapsedPct?: number | null;
    paceState?: string | null;
    meterText: string;
    height?: number;
    dim?: boolean;
    decorative?: boolean;
    okColor?: string | null;
    children?: Snippet;
    ariaHidden?: boolean;
    class?: string;
  }

  const {
    variant = 'segments',
    pct = null,
    segments = 20,
    filled = 0,
    scale,
    paceElapsedPct = null,
    paceState = null,
    meterText,
    height = 7,
    dim = false,
    decorative = false,
    okColor = null,
    children,
    ariaHidden = false,
    class: extra = '',
    ...rest
  }: Props = $props();

  const width = $derived(Math.min(100, Math.max(0, typeof pct === 'number' && Number.isFinite(pct) ? pct : 0)));
  const pace = $derived(
    !decorative && typeof paceElapsedPct === 'number' && Number.isFinite(paceElapsedPct)
      ? Math.min(100, Math.max(0, paceElapsedPct))
      : null,
  );
  const markerOver = 0;
  const style = $derived(
    `--oc-gauge-h:${height}px;--oc-gauge-pace-over:${markerOver}px${okColor ? `;--oc-gauge-ok:${okColor}` : ''}${height < 4 ? ';--oc-gauge-ring:none;--oc-gauge-track:color-mix(in oklab, var(--oc-line-panel) 45%, var(--oc-ground-panel))' : ''}`,
  );
</script>

<span
  {...rest}
  class="oc-gauge {extra}"
  class:oc-gauge--dim={dim}
  data-variant={variant}
  data-scale={scale ?? ''}
  role={decorative || ariaHidden ? undefined : 'img'}
  aria-label={decorative || ariaHidden ? undefined : meterText}
  aria-hidden={decorative || ariaHidden ? 'true' : undefined}
  {style}
>
  {#if pace !== null}
    <span class="oc-gauge__pace" data-pace={paceState ?? ""} style="left:{pace}%" aria-hidden="true"></span>
  {/if}
  {#if variant === 'segments'}
    <SegmentedMeterBar {segments} {filled} {scale} {meterText} {height} {dim} decorative />
  {:else}
    <span class="oc-gauge__bar" aria-hidden="true"><span class="oc-gauge__fill" style="width:{width}%"></span>{@render children?.()}</span>
  {/if}
</span>
