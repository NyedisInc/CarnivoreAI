
<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import SearchField from '../../opscenter/ui/SearchField.svelte';
  import { floorSource } from '../../cplugs/sdk';
  import { createBoardData } from './board-data.svelte';
  import type { BoardScope } from './board-types';
  import { BOARD_VIEWS, VIEW_COMPONENTS, readView, writeView, type BoardView } from './views';
  import { boardFocus, isFresh } from './board-focus.svelte';

  type ScopeKind = BoardScope['kind'];
  const SCOPES: readonly ScopeKind[] = ['sysop', 'company', 'project'];

  let view = $state<BoardView>(readView());
  let scopeKind = $state<ScopeKind>('sysop');
  let pickedCompany = $state<number | null>(null);
  let pickedProject = $state<number | null>(null);
  let filter = $state<'all' | 'mine'>('all');
  let archivedOnly = $state(false);
  let search = $state('');

  const source = $derived(floorSource());
  const companyChoices = $derived([...source.companies].sort((a, b) => a.name.localeCompare(b.name)));
  const projectChoices = $derived([...source.projects].sort((a, b) => a.name.localeCompare(b.name)));
  const scope = $derived.by((): BoardScope => {
    if (scopeKind === 'company') {
      const id = pickedCompany ?? companyChoices[0]?.id ?? null;
      return id === null ? { kind: 'sysop' } : { kind: 'company', id };
    }
    if (scopeKind === 'project') {
      const id = pickedProject ?? projectChoices[0]?.id ?? null;
      return id === null ? { kind: 'sysop' } : { kind: 'project', id };
    }
    return { kind: 'sysop' };
  });

  $effect(() => {
    const want = boardFocus.request;
    if (!isFresh(want)) return;
    scopeKind = 'sysop';
    filter = 'all';
    archivedOnly = want.archived;
    search = '';
    view = 'swimlanes';
  });

  const data = createBoardData(() => ({ scope, filter, archived: archivedOnly ? 'only' : 'hide' }), () => search);
  const Current = $derived(VIEW_COMPONENTS[view]);

  function pickView(next: BoardView): void {
    view = next;
    writeView(next);
  }
</script>

<div class="sbb" data-swarm-board data-swarm-board-view={view}>
  <div class="sbb-bar">
    <div class="sbb-group" role="group" aria-label={t('swarm.board.scope')}>
      <span class="sbb-label">{t('swarm.board.scope')}</span>
      {#each SCOPES as kind (kind)}
        <button type="button" class="sbb-key" aria-pressed={scopeKind === kind} data-swarm-scope={kind} onclick={() => (scopeKind = kind)}>{t(`swarm.board.scope.${kind}`)}</button>
      {/each}
      {#if scopeKind === 'company' && companyChoices.length}
        <select class="oc-field sbb-select" aria-label={t('swarm.board.scope.company')} value={scope.kind === 'company' ? scope.id : ''}
                onchange={(e) => (pickedCompany = Number(e.currentTarget.value))}>
          {#each companyChoices as c (c.id)}<option value={c.id}>{c.name}</option>{/each}
        </select>
      {:else if scopeKind === 'project' && projectChoices.length}
        <select class="oc-field sbb-select" aria-label={t('swarm.board.scope.project')} value={scope.kind === 'project' ? scope.id : ''}
                onchange={(e) => (pickedProject = Number(e.currentTarget.value))}>
          {#each projectChoices as p (p.id)}<option value={p.id}>{p.name}</option>{/each}
        </select>
      {/if}
    </div>
    <div class="sbb-group" role="group" aria-label={t('swarm.board.show')}>
      <span class="sbb-label">{t('swarm.board.show')}</span>
      {#each ['all', 'mine'] as const as f (f)}
        <button type="button" class="sbb-key" aria-pressed={filter === f} data-swarm-filter={f} onclick={() => (filter = f)}>{t(`swarm.board.show.${f}`)}</button>
      {/each}
      <button type="button" class="sbb-key" aria-pressed={archivedOnly} data-swarm-archived onclick={() => (archivedOnly = !archivedOnly)}>{t('swarm.board.show.archived')}</button>
    </div>
    <div class="sbb-group" role="group" aria-label={t('swarm.board.views')} data-swarm-view-switch>
      <span class="sbb-label">{t('swarm.board.view')}</span>
      {#each BOARD_VIEWS as v (v)}
        <button type="button" class="sbb-key sbb-key--view" aria-pressed={view === v} data-swarm-view-key={v} onclick={() => pickView(v)}>{t(`swarm.board.view.${v}`)}</button>
      {/each}
    </div>
    <div class="sbb-search">
      <SearchField value={search} onInput={(next) => (search = next)} placeholder={t('swarm.board.search')} ariaLabel={t('swarm.board.search')} data-swarm-board-search="" />
    </div>
  </div>
  {#if data.status === 'loading' && !data.board}
    <p class="sbb-note" data-swarm-board-status="loading">{t('swarm.board.loading')}</p>
  {:else if data.status === 'off'}
    <p class="sbb-note" data-swarm-board-status="off">{t('swarm.board.off')}</p>
  {:else if data.status === 'error'}
    <p class="sbb-note sbb-note--bad" data-swarm-board-status="error">{t('swarm.board.error', { error: data.error ?? '' })}</p>
  {/if}
  {#if data.board}
    <Current {data} />
  {/if}
</div>

<style>
  @layer components {
    .sbb {
      container: swarm-board-shell / inline-size;
      min-width: 0;
      font-family: var(--font-mono);
    }
    .sbb-bar {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 12px 24px;
      min-height: 52px;
      padding: 8px 0;
      box-shadow: 0 1px 0 var(--oc-line-rule);
    }
    .sbb-group {
      display: flex;
      align-items: center;
      gap: 4px;
    }
    .sbb-label {
      margin-right: 4px;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-label);
      letter-spacing: 0.14em;
      text-transform: uppercase;
    }
    .sbb-key {
      --_bd: var(--oc-line-rule);
      padding: 4px 11px;
      border: 1px solid var(--_bd);
      border-radius: var(--oc-radius-sm);
      background: transparent;
      color: var(--oc-text-secondary);
      font: inherit;
      font-size: var(--oc-fs-label);
      letter-spacing: 0.1em;
      text-transform: uppercase;
      white-space: nowrap;
      cursor: pointer;
    }
    .sbb-key--view {
      --_bd: transparent;
    }
    .sbb-key:hover {
      color: var(--oc-text-bright);
    }
    .sbb-key[aria-pressed='true'] {
      --_bd: var(--oc-cyan);
      background: color-mix(in srgb, var(--oc-cyan) 12%, transparent);
      color: var(--oc-cyan);
    }
    .sbb-select {
      max-width: 220px;
      margin-left: 4px;
      padding: 3px 8px;
      font-size: var(--oc-fs-label);
    }

    .sbb-search {
      flex: 0 1 240px;
      min-width: 180px;
      margin-left: auto;
    }
    @container swarm-board-shell (max-width: 720px) {
      .sbb-search {
        flex-basis: 100%;
        margin-left: 0;
      }
    }
    .sbb-search :global(.oc-page__search) {
      display: flex;
    }
    .sbb-search :global(.oc-field) {
      width: 100%;
      padding: 5px 10px;
      font-size: var(--oc-fs-body);
    }
    .sbb-note {
      margin: 20px 0 0;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-body);
    }
    .sbb-note--bad {
      color: var(--oc-coral);
    }
  }
</style>
