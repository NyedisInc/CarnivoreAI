<script lang="ts" module>
  export { HIT_ID_PREFIX, RESULTS_ID } from './ids';
</script>

<script lang="ts">
  /*  hidden  */
  import { resourcePush } from '../resource-push/boot';
  import { t } from '../i18n/index.svelte';
  import type { DrawerSearchController } from './provider-types';
  import LayoutToggle from './LayoutToggle.svelte';
  import ResultsList from './ResultsList.svelte';
  import { DeepSearchController, KIND_FILTERS, MIN_QUERY_CHARS } from './deepsearch.svelte';
  import { HIT_ID_PREFIX } from './ids';
  import { asScope, scopeKey } from './scope-api';
  import { countLine, staleLine } from './result-model';
  import './results.css';

  interface Props {
    controller: DrawerSearchController;
  }
  let { controller: given }: Props = $props();
  const controller = $derived(given as DeepSearchController);

  let rootEl = $state<HTMLElement | null>(null);

  const EXPORTS_TOPIC = 'exports';

  $effect(() => {
    const live = controller;
    return resourcePush().onChange((topics) => {
      if (topics.includes(EXPORTS_TOPIC)) void live.refreshExports();
    });
  });

  $effect(() => {
    if (controller.keyMoves === 0 || controller.active < 0) return;
    const id = `${HIT_ID_PREFIX}${controller.active}`;
    if (!rootEl) return;
    const el = rootEl.querySelector(`#${id}`) as HTMLElement | null;
    el?.scrollIntoView?.({ block: 'nearest' });
  });

  function statusText(): string {
    switch (controller.phase) {
      case 'short':
        return t('deepsearch.too_short', { count: MIN_QUERY_CHARS });
      case 'searching':
        return t('deepsearch.searching');
      case 'failed':
        return t('deepsearch.failed');
      case 'done':
        if (controller.total === 0) return t(controller.noMatchesKey, { query: controller.query.trim() });
        return countLine(controller.matches, controller.total, t);
      default:
        return '';
    }
  }

  function ingestText(): string {
    const ingest = controller.ingest;
    if (!ingest || controller.phase !== 'done') return '';
    if (ingest.state === 'stalled') return t('deepsearch.stalled_fts');
    if (ingest.backlogFiles > 0) return t('deepsearch.behind', { files: ingest.backlogFiles });
    if (ingest.indexScope && ingest.indexScope !== 'all') {
      return t('deepsearch.scope_note', { scope: t(scopeKey(asScope(ingest.indexScope))) });
    }
    return '';
  }

  const stalled = $derived(controller.ingest?.state === 'stalled' && controller.phase === 'done');
  const barShown = $derived(controller.phase === 'done' || controller.phase === 'searching');
  const chipsShown = $derived(barShown && controller.layout === 'best' && controller.filterable && controller.scope === null);
</script>

<div class="dps" data-testid="deepsearch" bind:this={rootEl}>
  <div class="dps__bar">
    <p class="dps__status" role="status" aria-live="polite">{statusText()}</p>
    {#if barShown}<LayoutToggle value={controller.layout} onChange={(l) => controller.setLayout(l)} />{/if}
  </div>
  {#if controller.phase === 'done' && staleLine(controller.stale.length, t)}
    <p class="dps__status dps__status--note" data-testid="deepsearch-stale">{staleLine(controller.stale.length, t)}</p>
  {/if}
  {#if controller.phase === 'done' && controller.peerDown.length > 0}
    {@const waiting = controller.peerDown.filter((p) => p.notReady)}
    {@const silent = controller.peerDown.filter((p) => !p.notReady)}
    {#if silent.length > 0}
      <p class="dps__peer-down" data-testid="deepsearch-peer-down">{t('deepsearch.peer_down', { computers: silent.map((p) => p.label).join(', ') })}</p>
    {/if}
    {#if waiting.length > 0}
      <p class="dps__peer-down" data-testid="deepsearch-peer-not-ready">{t('deepsearch.peer_not_ready', { computers: waiting.map((p) => p.label).join(', ') })}</p>
    {/if}
  {/if}
  {#if ingestText()}
    <p class="dps__ingest" class:dps__ingest--stalled={stalled} data-testid="deepsearch-ingest">{ingestText()}</p>
  {/if}
  {#if controller.scope}
    <div class="dps__scope" data-testid="deepsearch-scope">
      <span class="dps__scope-name">{t('deepsearch.scope_bar', { name: controller.scope.name })}</span>
      <button type="button" class="dps__linkbtn" onmousedown={(e) => e.preventDefault()} onclick={() => controller.clearScope()}>{t('deepsearch.scope_clear')}</button>
    </div>
  {/if}
  {#if chipsShown}
    <div class="dps__chips" role="group" aria-label={t('deepsearch.filter.label')} data-testid="deepsearch-chips">
      {#each KIND_FILTERS as kind (kind)}
        <button type="button" class="dps__chip" class:is-on={controller.kind === kind} aria-pressed={controller.kind === kind} data-kind={kind}
          onmousedown={(e) => e.preventDefault()} onclick={() => controller.setKind(kind)}>{t(`deepsearch.filter.${kind}`)}</button>
      {/each}
    </div>
  {/if}
  {#if controller.actionNote}
    <p class="dps__status dps__status--note" role="status" data-testid="deepsearch-action-note">{controller.actionNote}</p>
  {/if}
  {#if controller.phase === 'done' && controller.groups.length > 0}
    <ResultsList {controller} layout={controller.layout} />
    {#if controller.hasMore}
      <button type="button" class="modal-btn modal-btn-secondary dps__more" disabled={controller.loadingMore}
        onmousedown={(e) => e.preventDefault()} onclick={() => void controller.more()}>{t('deepsearch.more')}</button>
    {/if}
    <p class="dps__keys">{t('deepsearch.keys')}</p>
  {/if}
</div>
