<script lang="ts">
  /*  hidden  */
  import { onMount } from 'svelte';
  import { visibilityObserver } from '../visibility-observer';
  import Icon from '../../opscenter/ui/Icon.svelte';
  import StatusLed from '../StatusLed.svelte';
  import { t } from '../i18n/index.svelte';
  import { readChoice, writeChoice } from '../ui/prefs.svelte';
  import { floorFeedRows } from '../drawer/floor-feed.svelte';
  import { countAgents, type CountKind } from '../drawer/agent-counts';
  import { activeCountFilter, toggleCountFilter } from '../drawer/count-filter.svelte';
  import { packMachines } from '../pack-machines/pack-machines-store.svelte';
  import { acquireStatsFeed, statsFeed } from '../stats-feed/store.svelte';
  import { chartBars, compact, mergeBars, missingSpan, nextUnit, nextWindow, rateIn } from '../stats-feed/rate';
  import { FEED_WINDOWS, RATE_UNITS, type FeedBody, type FeedWindow, type RateUnit } from '../stats-feed/types';
  import { DRAWER_STATS_RATE_KEY, DRAWER_STATS_WINDOW_KEY } from './drawer-tabs';

  const WORDS = ['unavailable', 'stats_off', 'plugin_off', 'needs_approval', 'paused'] as const;
  const COUNT_KINDS: readonly CountKind[] = ['active', 'working', 'unread'];
  const RELEASE_MS = 5000;
  const CHART_H = 16;
  const BAR_PX = 2;
  const BAR_GAP_PX = 1;
  const MAX_BARS = 16;
  /* padding */
  const CHART_FIXED_PX = 30;
  const MIN_BARS = 4;
  const READ_WORDS: Readonly<Record<string, string>> = { 'signed-out': 'signed_out', unavailable: 'no_route', error: 'read_failed' };

  let { feed = undefined }: { feed?: FeedBody } = $props();

  let unit = $state<RateUnit>(readChoice(DRAWER_STATS_RATE_KEY, RATE_UNITS, 'min'));
  let win = $state<FeedWindow>(readChoice(DRAWER_STATS_WINDOW_KEY, FEED_WINDOWS, '1h'));
  let visible = $state(false);
  let root: HTMLElement | undefined = $state();
  let tokensEl: HTMLElement | undefined = $state();
  let rateEl: HTMLElement | undefined = $state();
  let barCap = $state(MAX_BARS);

  const counts = $derived(countAgents(floorFeedRows()));
  const filter = $derived(activeCountFilter());
  const packSize = $derived(packMachines.data?.machines.length ?? 0);
  const res = $derived(feed ? null : statsFeed(win));
  const fresh = $derived(feed ?? res?.data ?? null);
  const failed = $derived(res ? res.status in READ_WORDS : false);
  const readWord = $derived(res ? (READ_WORDS[res.status] ?? null) : null);
  let held = $state<FeedBody | null>(null);
  $effect(() => {
    if (fresh) held = fresh;
  });
  const body = $derived(fresh ?? held);
  const word = $derived(readWord ?? (body && (WORDS as readonly string[]).includes(body.state) ? body.state : null));
  const rate = $derived(word ? null : rateIn(body, unit));
  const bars = $derived(word || !body ? [] : mergeBars(chartBars(body), barCap, body.bucket_seconds));
  const peak = $derived(Math.max(1, ...bars.map((b) => b.total ?? 0)));
  const dim = $derived(body?.state === 'catching_up' || (fresh === null && held !== null));
  const missing = $derived(word ? null : missingSpan(body));
  const band = $derived.by(() => {
    if (!missing) return null;
    const first = bars.findIndex((b) => b.end > missing.from);
    return first < 0 ? null : { left: first * (BAR_PX + BAR_GAP_PX) };
  });

  $effect(() => {
    if (!visible) held = null;
  });

  $effect(() => {
    const host = tokensEl;
    const readout = rateEl;
    if (!host || !readout || typeof ResizeObserver === 'undefined') return;
    const fit = (): void => {
      const room = host.clientWidth - readout.offsetWidth - CHART_FIXED_PX;
      barCap = Math.max(0, Math.min(MAX_BARS, Math.floor((room + BAR_GAP_PX) / (BAR_PX + BAR_GAP_PX))));
    };
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(host);
    ro.observe(readout);
    return () => ro.disconnect();
  });

  $effect(() => (visible && !feed ? acquireStatsFeed(win) : undefined));

  onMount(() => {
    const Observer = visibilityObserver();
    if (!root || !Observer) {
      visible = true;
      return;
    }
    let timer: ReturnType<typeof setTimeout> | undefined;
    const io = new Observer((entries) => {
      const on = entries[entries.length - 1]?.isIntersecting ?? false;
      if (timer !== undefined) clearTimeout(timer);
      timer = undefined;
      if (on) visible = true;
      else timer = setTimeout(() => { visible = false; }, RELEASE_MS);
    });
    io.observe(root);
    return () => {
      io.disconnect();
      if (timer !== undefined) clearTimeout(timer);
    };
  });

  function cycleRate(): void {
    unit = nextUnit(unit);
    writeChoice(DRAWER_STATS_RATE_KEY, unit);
  }
  function cycleWindow(): void {
    win = nextWindow(win);
    writeChoice(DRAWER_STATS_WINDOW_KEY, win);
  }
</script>

<div class="dst-row" data-tooltip-off bind:this={root} data-state={word ?? body?.state ?? 'pending'} data-held={failed || (fresh === null && held !== null) ? 'true' : undefined}>
  <div class="dst-field" role="group" aria-label={t('drawer.stats.label')}>
    <div class="dst-counts">
      {#if packSize > 1}
        <span class="dst-pack" aria-label={t('drawer.stats.pack', { count: packSize })}>
          <Icon name="wolf" size={12} /><span class="dst-num">{packSize}</span>
        </span>
      {/if}
      {#each COUNT_KINDS as kind (kind)}
        <button
          type="button"
          class="dst-count" data-btn="quiet"
          data-kind={kind}
          data-filter={filter === kind ? 'on' : undefined}
          aria-pressed={filter === kind}
          aria-label={t(`drawer.stats.${kind}`, { count: counts[kind] })}
          onclick={() => toggleCountFilter(kind)}
        >
          {#if kind === 'active'}<Icon name="bot" size={12} />{:else if kind === 'working'}<StatusLed status="working" size="10px" />{:else}<StatusLed status="idle" unread={true} size="10px" />{/if}<span class="dst-num">{counts[kind]}</span>
        </button>
      {/each}
    </div>
    <div class="dst-tokens" class:dst-dim={dim} bind:this={tokensEl}>
      {#if word}
        <span class="dst-word" data-word={word}>{t(`drawer.stats.state.${word}`)}</span>
      {:else if !body}
        <span class="dst-word">{t('drawer.stats.pending')}</span>
      {:else}
        <button type="button" class="dst-act dst-rate" data-btn="quiet" bind:this={rateEl} aria-label={t('drawer.stats.rate.aria', { unit: t(`drawer.stats.unit.${unit}`) })} onclick={cycleRate}>
          <span class="dst-arrow"><Icon name="chevron-up" size={10} /></span>
          <span class="dst-figure">{rate ? compact(rate.out) : t('drawer.stats.none')}</span>
          <span class="dst-slash">/</span>
          <span class="dst-figure">{rate ? compact(rate.in) : t('drawer.stats.none')}</span>
          <span class="dst-arrow"><Icon name="chevron-down" size={10} /></span>
          <span class="dst-unit">{t(`drawer.stats.unit.${unit}`)}</span>
          <span class="dst-unit-short">{t(`drawer.stats.unit_short.${unit}`)}</span>
          {#if missing}<span class="dst-flag" data-cue={missing.down ? 'down' : 'partial'}></span>{/if}
        </button>
        {#if barCap >= MIN_BARS}
        <button type="button" class="dst-act dst-chart" data-btn="quiet" aria-label={t('drawer.stats.window.aria', { window: t(`drawer.stats.window.${win}`) })} onclick={cycleWindow}>
          <span class="dst-bars" aria-hidden="true">
            {#each bars as bar (bar.at)}
              {#if bar.total === null}
                <span class="dst-bar dst-bar--gap"></span>
              {:else}
                <span class="dst-bar" class:dst-bar--zero={bar.total === 0} style={`height:${bar.total === 0 ? 1 : Math.max(2, Math.round((bar.total / peak) * CHART_H))}px`}></span>
              {/if}
            {/each}
            {#if band}<span class="dst-band" data-cue={missing?.down ? 'down' : 'partial'} style={`left:${band.left}px`}></span>{/if}
          </span>
          <span class="dst-win">{t(`drawer.stats.window.short.${win}`)}</span>
        </button>
        {/if}
      {/if}
    </div>
  </div>
</div>

<style>
  @layer components {
    /* padding */
    .dst-row {
      container-type: inline-size;
      display: flex;
      align-items: center;
      gap: var(--oc-space-2);
      padding: var(--oc-space-2) var(--oc-space-3);
      background: var(--oc-ground-chrome);
      border-bottom: var(--oc-border) solid var(--oc-line-panel);
    }
    .dst-field {
      display: flex;
      align-items: stretch;
      flex: 1 1 auto;
      min-width: 0;
      height: var(--drawer-field-h, 24px);
      box-sizing: border-box;
      font-family: var(--font-mono);
      font-size: var(--oc-fs-label);
      color: var(--oc-text-secondary);
      overflow: hidden;
    }
    .dst-counts {
      display: inline-flex;
      align-items: center;
      flex: 0 0 auto;
      gap: var(--oc-space-2);
      padding: 0 var(--oc-space-2) 0 0;
      white-space: nowrap;
    }
    .dst-count {
      min-height: auto;
      transition: initial;
      display: inline-flex;
      align-items: center;
      gap: var(--oc-space-1);
      margin: 0;
      padding: 0 var(--oc-space-1);
      height: 18px;
      border: 1px solid transparent;
      border-radius: var(--oc-radius);
      background: transparent;
      color: var(--oc-text-secondary);
      font: inherit;
      cursor: pointer;
    }
    .dst-count:hover {
      color: var(--oc-text-primary);
    }
    .dst-count[data-filter='on'] {
      border-color: var(--oc-yellow-bright);
      color: var(--oc-text-primary);
    }
    .dst-pack {
      display: inline-flex;
      align-items: center;
      gap: var(--oc-space-1);
      padding: 0 var(--oc-space-1);
      color: var(--oc-text-secondary);
    }
    .dst-num {
      font-variant-numeric: tabular-nums;
      color: var(--oc-text-primary);
    }
    .dst-tokens {
      display: flex;
      align-items: stretch;
      justify-content: flex-end;
      flex: 1 1 auto;
      min-width: 0;
      overflow: hidden;
    }
    .dst-dim {
      opacity: 0.6;
    }
    .dst-word {
      align-self: center;
      padding: 0 var(--oc-space-2);
      color: var(--oc-text-muted);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .dst-act {
      display: inline-flex;
      align-items: center;
      flex: 0 0 auto;
      gap: 0;
      height: 100%;
      min-height: 0;
      margin: 0;
      padding: 0 var(--oc-space-2);
      border: 0;
      border-radius: 0;
      border-left: 1px solid var(--oc-line-rule);
      background: transparent;
      color: var(--oc-text-secondary);
      font: inherit;
      text-transform: lowercase;
      white-space: nowrap;
      cursor: pointer;
    }
    .dst-act:hover {
      color: var(--oc-text-primary);
    }
    .dst-arrow {
      display: inline-flex;
      color: var(--oc-text-muted);
    }
    .dst-figure {
      text-transform: none;
      font-variant-numeric: tabular-nums;
      color: var(--oc-text-primary);
    }
    .dst-slash,
    .dst-unit,
    .dst-unit-short {
      color: var(--oc-text-muted);
    }
    .dst-unit,
    .dst-unit-short {
      margin-left: var(--oc-space-1);
    }
    .dst-unit-short {
      display: none;
    }
    .dst-bars {
      position: relative;
      display: flex;
      align-items: flex-end;
      height: 18px;
      gap: calc(var(--oc-space-1) / 4);
    }
    .dst-win {
      margin-left: var(--oc-space-1);
      color: var(--oc-text-muted);
    }
    .dst-bar {
      flex: 0 0 2px;
      width: 2px;
      background: var(--oc-spark);
    }
    .dst-band {
      position: absolute;
      top: 0;
      right: 0;
      bottom: 0;
      pointer-events: none;
      background: repeating-linear-gradient(135deg, var(--oc-text-muted) 0 1px, transparent 1px 3px);
      box-shadow: inset 0 -1px 0 var(--oc-text-muted);
    }
    .dst-band[data-cue='down'] {
      background: repeating-linear-gradient(135deg, var(--oc-coral) 0 1px, transparent 1px 3px);
      box-shadow: inset 0 -1px 0 var(--oc-coral);
    }
    .dst-flag {
      width: 4px;
      height: 4px;
      margin-left: var(--oc-space-1);
      background: var(--oc-text-muted);
    }
    .dst-flag[data-cue='down'] {
      background: var(--oc-coral);
    }
    .dst-bar--zero {
      background: var(--oc-spark-dim);
    }
    .dst-bar--gap {
      height: 100%;
      background: repeating-linear-gradient(135deg, var(--oc-line-rule) 0 1px, transparent 1px 3px);
    }
    @container (max-width: 360px) {
      .dst-unit {
        display: none;
      }
      .dst-unit-short {
        display: inline;
      }
    }
    /* padding */
    @container (max-width: 250px) {
      .dst-rate {
        padding: 0;
      }
      .dst-unit-short {
        margin-left: 0;
      }
      .dst-arrow :global(svg) {
        width: 8px;
        height: 8px;
      }
    }
    @media (max-width: 1023px) {
      .dst-act {
        position: relative;
        min-height: 0;
      }
      .dst-act::after {
        content: '';
        position: absolute;
        top: 50%;
        left: 0;
        right: 0;
        height: var(--oc-tap, 44px);
        transform: translateY(-50%);
      }
    }
  }
</style>
