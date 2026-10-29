<script lang="ts">
  import PageToolbar from '../../opscenter/ui/PageToolbar.svelte';
  import HighlightTiles, { type HighlightTile } from '../../opscenter/ui/HighlightTiles.svelte';
  import HighlightPair from '../../opscenter/ui/HighlightPair.svelte';
  import RankPanel, { type RankRow } from '../../opscenter/ui/RankPanel.svelte';
  import type { PageView } from '../../opscenter/ui/page-view';
  import { t } from '../../lib/i18n/index.svelte';

  let { part = 'toolbar' }: { part?: 'toolbar' | 'tiles' | 'pair' } = $props();

  let query = $state('');
  let view = $state<PageView>('ledger');
  let facets = $state({ project: 'all', agent: 'all', state: 'all' });
  let sort = $state('recent');
  const all = [{ value: 'all', label: 'all' }];
  const tiles: HighlightTile[] = [
    { id: 'a', name: 'cloudecode', figure: '7', unit: 'running', line: '3 asleep · 12 closed', activity: [1, 2, 2, 4, 3, 5, 6, 4, 7, 8, 6, 9, 7, 10] },
    { id: 'b', name: 'argent', figure: '4', unit: 'running', line: '1 asleep · 9 closed', activity: [0, 1, 1, 0, 2, 3, 2, 4, 3, 2, 5, 4, 3, 4] },
    { id: 'c', name: 'a-project-with-a-very-long-name', figure: '3', unit: 'running', line: '6 asleep · 22 closed · 4 more', activity: [2, 2, 3, 1, 1, 2, 0, 2, 3, 3, 2, 1, 2, 3] },
    { id: 'd', name: 'docs', figure: '2', unit: 'running', line: '0 asleep · 3 closed', activity: [] },
    { id: 'e', name: 'hosted', figure: '1', unit: 'running', line: '2 asleep · 5 closed', activity: [0, 0, 1, 0, 0, 1, 1, 0, 0, 2, 1, 0, 1, 1] },
  ];
  const needs: RankRow[] = [
    { id: 'n1', name: 'migrate the ledger', line: 'cloudecode · question', icon: 'chat', tags: ['claude'], metric: { value: '14', unit: 'm waiting' } },
    { id: 'n2', name: 'review the diff', line: 'argent · finished', icon: 'check', tags: ['codex'], metric: { value: '9', unit: 'm waiting' } },
  ];
  const working: RankRow[] = [
    { id: 'w1', name: 'build the page kit', line: 'cloudecode · working', icon: 'activity', tags: ['claude'], metric: { value: '3', unit: 'm turn' } },
    { id: 'w2', name: 'port the drawer', line: 'argent · working', icon: 'activity', tags: ['claude'], metric: null },
  ];
  const notMeasured = t('opscenter.session.mark.not_measured');
</script>

{#if part === 'toolbar'}
  <PageToolbar
    {query}
    onQuery={(next) => (query = next)}
    searchPlaceholder="search sessions"
    facets={[
      { id: 'project', label: 'project', value: facets.project, options: all },
      { id: 'agent', label: 'agent', value: facets.agent, options: [...all, { value: 'claude', label: 'claude' }, { value: 'codex', label: 'codex' }] },
      { id: 'state', label: 'state', value: facets.state, options: all },
    ]}
    onFacet={(id, value) => (facets = { ...facets, [id]: value })}
    sort={{ label: 'sort', value: sort, options: [{ value: 'recent', label: 'recent' }, { value: 'name', label: 'name' }] }}
    onSort={(next) => (sort = next)}
    {view}
    onView={(next) => (view = next)}
    {t}
  />
{:else if part === 'tiles'}
  <HighlightTiles label="busiest projects" caption="running sessions now" {tiles} sparkLabel="activity, last 14 days" />
{:else}
  <HighlightPair label="what matters now" caption="sessions">
    {#snippet first()}<RankPanel label="needs you" rows={needs} ranked columns={{ name: 'session', metric: 'waiting' }} viewAll="view all" onViewAll={() => {}} {notMeasured} />{/snippet}
    {#snippet second()}<RankPanel label="working now" rows={working} ranked columns={{ name: 'session', metric: 'turn age' }} viewAll="view all" onViewAll={() => {}} {notMeasured} />{/snippet}
  </HighlightPair>
{/if}
