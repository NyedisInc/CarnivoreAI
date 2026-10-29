
<script lang="ts">
  import type { Snippet } from 'svelte';
  import { statTileClass, type StatTileKind, type StatTileMode, type StatTileSize, type StatTileTone } from './classes';

  interface Props {
    label: string;
    figure?: string;
    unit?: string;
    kind?: StatTileKind;
    size?: StatTileSize;
    mode?: StatTileMode;
    delta?: string;
    deltaNote?: string;
    deltaTone?: StatTileTone;
    notice?: string;
    meter?: number | null;
    sub?: string;
    onsub?: () => void;
    subAttrs?: Record<string, string>;
    subLive?: boolean;
    tone?: string;
    meta?: string;
    figurePx?: number;
    framed?: boolean;
    display?: boolean;
    editing?: boolean;
    id?: string;
    figureLabel?: string;
    ariaLabel?: string;
    element?: HTMLElement | undefined;
    icon?: Snippet;
    spark?: Snippet;
    foot?: Snippet;
    empty?: Snippet;
  }

  let {
    label, figure = '', unit = '', kind = 'value', size = 'regular', mode = 'flat', delta = '', deltaNote = '',
    deltaTone = 'none', notice = '', meter = null, sub = '', onsub, subAttrs, subLive = false, tone, meta = '', figurePx, framed = true,
    display = false, editing = false, id, figureLabel, ariaLabel, element = $bindable(), icon, spark, foot, empty,
  }: Props = $props();

  const line = $derived(mode === 'line');
  const regular = $derived(size === 'regular');
  const style = $derived(
    [tone ? `--_stat-tone: var(${tone})` : '', figure ? `--_stat-chars: ${figure.length}` : '', figurePx ? `--_stat-figure: ${figurePx}px` : ''].filter(Boolean).join('; ') || undefined,
  );
</script>

<section
  bind:this={element}
  class={statTileClass({ size, mode, kind, framed, display, editing })}
  data-tile={id}
  {style}
  aria-label={ariaLabel ?? (label || undefined)}
>
  {#if label || icon || (meta && !line)}
    <div class="oc-stat-tile__head">
      <span class="oc-stat-tile__lead">
        {#if icon}<span class="oc-stat-tile__icon" aria-hidden="true">{@render icon()}</span>{/if}
        {#if label}<span class="oc-stat-tile__label">{label}</span>{/if}
      </span>
      {#if meta && !line}<span class="oc-stat-tile__meta">{meta}</span>{/if}
    </div>
  {/if}
  {#if empty}
    {@render empty()}
  {:else}
    <div class="oc-stat-tile__body">
      <span
        class="oc-stat-tile__figure"
        class:oc-stat-tile__figure--dim={kind === 'dim'}
        class:oc-stat-tile__figure--note={kind === 'note'}
        aria-label={figureLabel}>{figure}</span
      >
      {#if unit}<span class="oc-stat-tile__unit">{unit}</span>{/if}
      {#if regular && !line && delta}
        <span class="oc-stat-tile__delta oc-stat-tile__delta--{deltaTone}"><b>{delta}</b>{#if deltaNote} <span>{deltaNote}</span>{/if}</span>
      {/if}
    </div>
    {#if notice && !line}<p class="oc-stat-tile__notice" role="alert">{notice}</p>{/if}
    {#if spark && !line}<span class="oc-stat-tile__spark">{@render spark()}</span>{/if}
    {#if (meter !== null || sub) && !line}
      <span class="oc-stat-tile__foot">
        {#if meter !== null}
          <span class="oc-stat-tile__meter" aria-hidden="true"><span class="oc-stat-tile__meter-fill" style:width={`${meter}%`}></span></span>
        {/if}
        {#if sub && onsub}<button type="button" class="oc-stat-tile__sub oc-stat-tile__sub--go" {...subAttrs} onclick={onsub}>{sub}</button>
        {:else if sub}<span class="oc-stat-tile__sub" data-live-clock={subLive ? '' : undefined}>{sub}</span>{/if}
      </span>
    {/if}
    {#if foot && !line}<div class="oc-stat-tile__extra">{@render foot()}</div>{/if}
  {/if}
</section>
