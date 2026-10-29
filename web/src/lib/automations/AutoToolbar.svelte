
<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import Button from '../base/Button.svelte';
  import Field from '../base/Field.svelte';
  import IconButton from '../base/IconButton.svelte';
  import Segmented from '../base/Segmented.svelte';
  import Select, { type SelectChoice } from '../base/Select.svelte';
  import Tag from '../base/Tag.svelte';
  import Toolbar from '../base/Toolbar.svelte';
  import { DESC_FIRST, PILL_STATUSES, pillWords, SORT_KEYS, type Pill, type SortKey } from './logic/list';
  import { allRows, narrowed, resetFilters, view } from './list-state.svelte';
  import { data } from './page-store.svelte';
  import { countWords } from './logic/words';

  let { shown }: { shown: number } = $props();

  const kinds = $derived([...new Set(allRows().map((r) => r.kindLabel))].sort());
  const sortLabel = (k: SortKey): string => (k === 'light' ? t('automations.page.sort.attention') : t(`automations.page.col.${k}`));
  const filterChoices = $derived<SelectChoice[]>([
    { value: '', label: t('automations.page.filter.add') },
    { group: t('automations.page.filter.group_last_run'), options: PILL_STATUSES.map((s) => ({ value: `status|${s}`, label: pillWords({ k: 'status', v: s }) })) },
    { group: t('automations.page.filter.group_kind'), options: kinds.map((k) => ({ value: `kind|${k}`, label: pillWords({ k: 'kind', v: k }) })) },
  ]);
  const sortChoices = $derived<SelectChoice[]>(SORT_KEYS.map((k) => ({ value: k, label: sortLabel(k) })));
  const DENSITY = $derived(['comfortable', 'compact'].map((d) => ({ value: d, label: t(`automations.page.density.${d}`), attrs: { 'data-dens': d } })));

  function addPill(value: string): void {
    const [k, ...rest] = value.split('|');
    if (!k || (k !== 'status' && k !== 'kind')) return;
    const pill = { k, v: rest.join('|') } as Pill;
    if (!view.pills.some((p) => p.k === pill.k && p.v === pill.v)) view.pills = [...view.pills, pill];
  }

  let adding = $state('');
  $effect(() => {
    if (adding === '') return;
    addPill(adding);
    adding = '';
  });

  function sortBy(value: string): void {
    const k = value as SortKey;
    view.sort = { k, d: DESC_FIRST.has(k) ? -1 : 1 };
  }
</script>

{#snippet findPart()}
  <Field
    variant="search"
    label={t('automations.page.find.aria')}
    bind:value={view.q}
    data-auto-find
    placeholder={t('automations.page.find.placeholder')}
    clearLabel={t('automations.page.find.clear')}
    autocomplete="off"
    spellcheck={false}
  />
{/snippet}
{#snippet facetsPart()}
  <Select size="sm" bind:value={adding} options={filterChoices} data-auto-addf aria-label={t('automations.page.filter.add_aria')} />
  <Select size="sm" value={view.sort.k} options={sortChoices} data-auto-sort aria-label={t('automations.page.sort.aria')} onchange={(e) => sortBy(e.currentTarget.value)} />
  <Button
    size="sm"
    data-auto-dir
    aria-label={t(view.sort.d > 0 ? 'automations.page.sort.asc_aria' : 'automations.page.sort.desc_aria')}
    onclick={() => (view.sort = { k: view.sort.k, d: view.sort.d > 0 ? -1 : 1 })}
  >
    {t(view.sort.d > 0 ? 'automations.page.sort.asc' : 'automations.page.sort.desc')}
  </Button>
{/snippet}
{#snippet metaPart()}
  <Segmented label={t('automations.page.density.aria')} options={DENSITY} bind:value={() => view.dens, (d) => (view.dens = d as 'comfortable' | 'compact')} />
  <Button size="sm" data-auto-clear hidden={!narrowed()} onclick={resetFilters}>{t('automations.page.clear')}</Button>
  <span class="ap-lt__count ap-num" data-auto-count aria-live="polite">
    {t('automations.page.toolbar.count', { n: shown, total: countWords('automations.page.count.automation', data.automations.length) })}
  </span>
{/snippet}
{#snippet pillsPart()}
  <div class="ap-pills" aria-label={t('automations.page.pills.aria')}>
    {#each view.pills as pill, i (pill.k + '|' + pill.v)}
      <Tag data-auto-pill>
        {pillWords(pill)}
        <IconButton variant="close" icon="close" iconSize={10} data-unpill={i} label={t('automations.page.pill.remove', { name: pillWords(pill) })} onclick={() => (view.pills = view.pills.filter((_, j) => j !== i))} />
      </Tag>
    {/each}
  </div>
{/snippet}

<Toolbar
  band
  wrap
  class="ap-lt"
  role="search"
  label={t('automations.page.toolbar.aria')}
  data-auto-toolbar=""
  search={findPart}
  filters={facetsPart}
  end={metaPart}
  below={view.pills.length ? pillsPart : undefined}
/>
