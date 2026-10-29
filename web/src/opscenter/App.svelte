<script lang="ts">
  import TopBar from './shell/TopBar.svelte';
  import HomeOpenMenu from './shell/HomeOpenMenu.svelte';
  import GridSurface from './engine/GridSurface.svelte';
  import { GUTTER } from './engine/tracks';
  import { observeCell, sizeOf } from './engine/observe.svelte';
  import CellHost from './CellHost.svelte';
  import FlyLayer from './engine/FlyLayer.svelte';
  import LiveRegion from './engine/LiveRegion.svelte';
  import { homeLayout } from './engine/layout.svelte';
  import { startClock } from './lib/frozen-clock.svelte';
  import { navAnchors } from './engine/navAnchors.svelte';
  import { viewport, watchStillness, watchViewport } from './engine/viewport.svelte';
  import { installFlushOnExit } from './engine/persist';
  import { auth, initAuth, startActivity, startEvents } from './api';
  import { startSwitchToasts } from '../lib/account-switch/switch-toast';
  import { startShapeAlertToasts } from '../lib/dev-shape-alert/shape-toast';
  import { startTripwireToasts } from '../lib/stats-tripwire/tripwire-toast';
  import { onMount } from 'svelte';
  import { t } from '../lib/i18n/index.svelte';
  import { analytics, applyStatsChanged, refreshAnalytics, seedHomeAnalytics } from './cells/analytics/state.svelte';
  import { followStatsFrames } from './cells/analytics/stats-frames';
  import EmptySpaceMenu from './layout-editor/EmptySpaceMenu.svelte';
  import { onContextMenu, onMenuKey } from './layout-editor/empty-space-menu.svelte';
  import { readOnlyStore } from './engine/wallboard';

  /* the home screen */
  let { popout = false, wallboard = false }: { popout?: boolean; wallboard?: boolean } = $props();

  const surfaceStore = wallboard ? readOnlyStore(homeLayout, () => sizeOf('content').height) : homeLayout;

  const showBar = $derived(!wallboard && (popout || viewport.phone));

  const showOpenMenu = $derived(!wallboard && !popout && !viewport.phone);

  $effect(() => startClock());
  $effect(() => watchViewport());
  $effect(() => watchStillness());
  $effect(() => installFlushOnExit());

  function refreshHomeAnalytics(): void {
    void refreshAnalytics().then(() => (popout ? undefined : seedHomeAnalytics(homeLayout)));
  }

  onMount(() => {
    initAuth();
    startEvents();
    refreshHomeAnalytics();
    const stopStatsFrames = followStatsFrames({
      refreshAll: refreshHomeAnalytics,
      apply: (changed) => void applyStatsChanged(changed),
    });
    startSwitchToasts();
    startShapeAlertToasts();
    startTripwireToasts();
    const stopActivity = startActivity();
    return () => { stopActivity(); stopStatsFrames(); };
  });
</script>

<div class="oc-app" class:oc-app-wallboard={wallboard} class:oc-app-bare={!wallboard && !showBar} class:oc-app-noticed={auth.state === 'unreachable' || (popout && auth.state === 'signed-out')}>
  {#if showBar}<TopBar {popout} />{/if}
  {#if showOpenMenu}<HomeOpenMenu />{/if}
  
  {#if popout && auth.state === 'signed-out'}
    <p class="oc-unreachable" role="status">{t('opscenter.popout.signed_out')}</p>
  {:else if auth.state === 'unreachable'}
    <p class="oc-unreachable" role="status">{t('opscenter.app.backend_unreachable')}</p>
  {/if}
  
  <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
  <main
    class="oc-content"
    {@attach observeCell('content')}
    bind:this={navAnchors.surface}
    tabindex={wallboard || popout ? undefined : 0}
    aria-label={wallboard || popout ? undefined : t('opscenter.empty_menu.label')}
    oncontextmenu={wallboard || popout ? undefined : onContextMenu}
    onkeydown={wallboard || popout ? undefined : (event) => onMenuKey(event, event.currentTarget)}
  >
    
    {#if analytics.error}
      <p class="oc-analytics-error" role="alert">{analytics.error} <button type="button" onclick={refreshHomeAnalytics}>{t('analytics.retry')}</button></p>
    {/if}
    {#if wallboard && surfaceStore.state.layout.rows.length === 0}
      <p class="oc-wallboard-empty" role="status">{t('opscenter.wallboard.empty')}</p>
    {/if}
    <GridSurface gutter={GUTTER} store={surfaceStore}>
      {#snippet renderCell(slot)}
        <CellHost id={slot.id} store={surfaceStore} />
      {/snippet}
    </GridSurface>
  </main>
</div>



<LiveRegion store={homeLayout} />
{#if !popout && !wallboard}<EmptySpaceMenu />{/if}
<FlyLayer />

<style>
  @layer components {
    .oc-app-noticed {
      grid-template-rows: var(--oc-topbar) auto minmax(0, 1fr);
    }

    .oc-unreachable {
      margin: 0;
      padding: 6px 22px;
      background: var(--oc-ground-chrome);
      box-shadow: inset 0 -1px 0 0 var(--oc-line-chrome);
      font-size: var(--oc-fs-label);
      color: var(--oc-coral);
    }

    .oc-app-wallboard :global(.oc-gutter-band),
    .oc-app-wallboard :global(.oc-span-edge) {
      visibility: hidden;
      pointer-events: none;
    }

    .oc-app-wallboard :global(.oc-frame-corner),
    .oc-app-wallboard :global(.oc-frame-cornerwrap) {
      display: none;
    }

    .oc-app-wallboard :global(.oc-frame-title),
    .oc-app-wallboard :global(.oc-frame-strip) {
      pointer-events: none;
      cursor: default;
    }

    .oc-wallboard-empty { margin: var(--oc-space-4); color: var(--oc-text-muted); font: var(--oc-fs-label) var(--font-mono); text-transform: lowercase; letter-spacing: 0.08em; }

    .oc-analytics-error { margin: 0; padding: 6px var(--oc-space-3); color: var(--oc-coral); font-size: var(--oc-fs-label); }

    .oc-analytics-error button { border: 1px solid var(--oc-line-rule); color: var(--oc-text-primary); background: var(--oc-ground-raised); cursor: pointer; }
  }
</style>
