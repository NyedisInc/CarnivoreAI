<script lang="ts">
  import WarezTools from '../../lib/catalog/WarezTools.svelte';
  import CatalogCard from '../../lib/catalog/CatalogCard.svelte';
  import PacksShelf from '../../lib/catalog/PacksShelf.svelte';
  import SearchField from '../../opscenter/ui/SearchField.svelte';
  import type { ManagerView } from '../../lib/manager-frame/view-memory';
  import KindMark from '../../lib/catalog/KindMark.svelte';
  import VerdictMark from '../../lib/catalog/VerdictMark.svelte';
  import GradeBlock from '../../lib/catalog/GradeBlock.svelte';
  import AutoUpdateSwitch from '../../lib/catalog/AutoUpdateSwitch.svelte';
  import { cardView } from '../../lib/catalog/card';
  import { NO_FILTERS, type CatalogFilters } from '../../lib/catalog/filter';
  import type { InstallState } from '../../lib/catalog/install-actions';
  import { t } from '../../lib/i18n/index.svelte';

  let { part }: { part: 'toolbar' | 'cards' | 'packs' | 'grade' | 'toggle' | 'kinds' } = $props();
  let autoUpdate = $state(true);

  let query = $state('');
  let view = $state<ManagerView>('grid');
  let filters = $state<CatalogFilters>({ ...NO_FILTERS });

  const item = {
    id: 'nyedis/music-tools',
    kind: 'skill',
    name: 'music-tools',
    publisher: 'nyedis',
    latest: '1.2.0',
    card: { title: 'music tools', brief: 'tag, rename and sort an audio library', tags: ['audio', 'files'] },
  };

  const states: { label: string; state: InstallState; untrusted?: boolean }[] = [
    { label: 'idle', state: { kind: 'idle' } },
    { label: 'installed', state: { kind: 'installed' } },
    { label: 'update available', state: { kind: 'update-available' } },
    { label: 'verifying', state: { kind: 'verifying' } },
    { label: 'refused', state: { kind: 'refused', code: 'signature_invalid' } },
    { label: 'untrusted publisher', state: { kind: 'idle' }, untrusted: true },
  ];

  const swarmItems = [
    { ...item, id: 'nyedis/audio-swarm', kind: 'loadout', name: 'audio-swarm', card: { title: 'audio swarm', brief: 'the tag, rename and sort skills and the theme they were made with, in one install', tags: [] } },
    { ...item, id: 'carnivore/review-swarm', kind: 'loadout', publisher: 'carnivore', name: 'review-swarm', card: { title: 'review swarm', brief: 'a code review loadout', tags: [] } },
  ];

  const noop = (): void => {};
</script>

{#snippet searchField()}
  <SearchField value={query} onInput={(next) => (query = next)} ariaLabel={t('skill.search.label')} placeholder={t('skill.search.placeholder')} />
{/snippet}

{#if part === 'toolbar'}
  <div class="oc-titlebar__actions">
  <WarezTools
    search={searchField}
    {view}
    onView={(next) => (view = next)}
    sortKey="index"
    onSort={noop}
    {t}
  />
  </div>
{:else if part === 'cards'}
  <ul class="sg-card-grid">
    {#each states as s (s.label)}
      <li class="sg-card-cell">
        <span class="sg-caption">{s.label}</span>
        <CatalogCard
          card={cardView(item, s.untrusted === true)}
          state={s.state}
          {t}
          onInstall={noop}
          onUpdate={noop}
          onOpen={noop}
        />
      </li>
    {/each}
  </ul>
  <span class="sg-caption">list form (the skills page's 28px row, `list`)</span>
  <div class="sg-catalog-list">
    {#each states as s (s.label)}
      <CatalogCard
        list
        card={cardView(item, s.untrusted === true)}
        state={s.state}
        {t}
        onInstall={noop}
        onUpdate={noop}
        onOpen={noop}
      />
    {/each}
  </div>
{:else if part === 'kinds'}
  <ul class="sg-card-grid">
    {#each ['mod', 'skill', 'theme', 'plugin', 'loadout'] as kind (kind)}
      <li class="sg-card-cell">
        <span class="sg-caption">{kind}</span>
        <span class="sg-row">
          <KindMark {kind} size="sm" {t} />
          <KindMark {kind} size="md" {t} />
          <KindMark {kind} size="lg" {t} />
        </span>
      </li>
    {/each}
  </ul>
  <div class="sg-row">
    <VerdictMark verdict="clean" {t} />
    <VerdictMark verdict="flagged" {t} />
    <VerdictMark verdict="blocked" {t} />
    <VerdictMark verdict="unreadable" {t} />
  </div>
{:else if part === 'packs'}
  <PacksShelf cards={swarmItems.map((p) => cardView(p, false))} selectedId={null} {t} onSelect={noop} />
{:else if part === 'toggle'}
  <div class="sg-row sg-row--top">
    <AutoUpdateSwitch
      installed={{ install_id: 'demo', revision: 1, scope: 'global', auto_update: autoUpdate }}
      working={false}
      busy={false}
      {t}
      onToggle={(next) => (autoUpdate = next)}
    />
    <AutoUpdateSwitch
      installed={{ install_id: 'demo', revision: 1, scope: 'global', auto_update: false }}
      working={false}
      busy={true}
      {t}
      onToggle={noop}
    />
  </div>
{:else}
  <div class="sg-row sg-row--top">
    <GradeBlock grade={{ grade: 'A', checked: 12, failed: [], not_graded: [] }} {t} />
    <GradeBlock grade={{ grade: null, checked: null }} {t} />
    <GradeBlock grade={null} {t} />
  </div>
{/if}
