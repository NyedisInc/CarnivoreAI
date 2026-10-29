<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import { RAIL_BANDS, type RailBand, type RailEdge } from './rail-model';
  import { railOutSizes } from './rail-out-size.svelte';

  let { edge, aimed = null }: { edge: RailEdge; aimed?: RailBand | null } = $props();

  const side = $derived(edge === 'side');
  let winW = $state(typeof window === 'undefined' ? 1280 : window.innerWidth);
  let winH = $state(typeof window === 'undefined' ? 800 : window.innerHeight);
  const extent = $derived(railOutSizes.shown(edge, side ? winW : winH));

  const LABELS: Readonly<Record<RailEdge, Record<RailBand, string>>> = {
    side: { start: 'session_rail.band_start', end: 'session_rail.band_end' },
    bottom: { start: 'session_rail.band_start_bottom', end: 'session_rail.band_end_bottom' },
  };
</script>

<svelte:window bind:innerWidth={winW} bind:innerHeight={winH} />
<div class="rail-bands" class:rail-bands--side={side} class:rail-bands--bottom={!side} style={side ? `width: ${extent}px` : `height: ${extent}px`}
  data-rail-bands={edge} aria-hidden="true">
  {#each RAIL_BANDS as band (band)}
    <div class="rail-band" data-rail-band={band} data-aimed={aimed === band}>
      <span class="rail-band__label">{t(LABELS[edge][band])}</span>
    </div>
  {/each}
</div>

<style>
  @layer components {
    .rail-bands {
      position: absolute;
      z-index: 41;
      display: flex;
      justify-content: space-between;
      pointer-events: none;
    }

    .rail-bands--side {
      top: 0;
      right: 100%;
      bottom: 0;
      flex-direction: column;
    }

    .rail-bands--bottom {
      left: 0;
      right: 0;
      bottom: 100%;
      flex-direction: row;
    }

    .rail-band {
      display: flex;
      flex: 0 0 30%;
      align-items: center;
      justify-content: center;
      border: var(--oc-border) dashed var(--oc-cyan);
      background: color-mix(in oklab, var(--oc-cyan) 8%, transparent);
    }

    .rail-band[data-aimed='true'] {
      background: color-mix(in oklab, var(--oc-cyan) 22%, transparent);
    }

    .rail-band__label {
      color: var(--oc-text-dim);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-micro, 10px);
      letter-spacing: var(--oc-tracking-title, 0.8px);
    }

    .rail-band[data-aimed='true'] .rail-band__label {
      color: var(--oc-cyan);
    }
  }
</style>
