<!-- <button> role="button" -->
<script lang="ts">
  import { onMount } from 'svelte';
  import { authFetch } from '../../opscenter/api/auth.svelte';
  import { t } from '../i18n/index.svelte';
  import { requestFocusFeature } from './feature-focus.svelte';
  import type { FeatureCatalogItem } from './features-by-area';
  import FeatureDetail from './FeatureDetail.svelte';
  import MediaLightbox from './MediaLightbox.svelte';
  import {
    groupFeaturesByRelease,
    type FeatureChangeLine,
    type FeatureRelease,
    type FeaturesIndexResponse,
  } from './features-grouping';

  import { highlightSegments, parseQuery, type SearchMode } from './fuzzy-search';
  import { matchReleases, rowsOfRelease } from './releases-search';

  type ViewState = 'loading' | 'failed' | 'unavailable' | 'ready';

  interface Props {
    query?: string;
    onClearQuery?: () => void;
    fuzzy?: boolean;
  }

  const { query = '', onClearQuery, fuzzy = false }: Props = $props();
  const mode = $derived<SearchMode>(fuzzy ? 'fuzzy' : 'plain');

  const tokens = $derived(parseQuery(query));
  const searching = $derived(tokens.length > 0);

  let viewState: ViewState = $state('loading');
  let releases: FeatureRelease[] = $state([]);
  let openReleases: Record<string, boolean> = $state({});
  let expandedRows: Record<string, boolean> = $state({});
  let catalogById: Record<string, FeatureCatalogItem> = $state({});
  let lightbox: { src: string; alt: string; caption: string | undefined } | null = $state(null);

  onMount(() => {
    void load();
  });

  async function load(): Promise<void> {
    viewState = 'loading';
    try {
      const payload = await authFetch<FeaturesIndexResponse>('/feature-catalog');
      if (!payload.available) {
        viewState = 'unavailable';
        return;
      }
      releases = groupFeaturesByRelease(payload);
      openReleases = releases.length > 0 ? { [releases[0]!.name]: true } : {};
      const catalog = payload.catalog as unknown as FeatureCatalogItem[];
      catalogById = Object.fromEntries(catalog.map((item) => [item.id, item]));
      viewState = 'ready';
    } catch {
      viewState = 'failed';
    }
  }

  function rowsOf(release: FeatureRelease): FeatureChangeLine[] {
    return rowsOfRelease(release);
  }

  const shown = $derived(
    searching
      ? matchReleases(releases, tokens, catalogById, mode)
      : releases.map((release) => ({
          release,
          rows: rowsOf(release).map((row, index) => ({ row, index, bodyOnly: false })),
        })),
  );
  const matchCount = $derived(shown.reduce((n, entry) => n + entry.rows.length, 0));

  function toggleRelease(name: string): void {
    openReleases = { ...openReleases, [name]: !openReleases[name] };
  }

  function bodyIdFor(index: number): string {
    return `sidebar-help-release-${index}`;
  }

  function rowKey(releaseName: string, i: number): string {
    return `${releaseName}::${i}`;
  }

  function isRowExpanded(key: string, bodyOnly: boolean): boolean {
    return expandedRows[key] ?? (searching && bodyOnly);
  }

  function isReleaseOpen(name: string): boolean {
    return searching || openReleases[name] === true;
  }

  function toggleRow(key: string): void {
    expandedRows = { ...expandedRows, [key]: !expandedRows[key] };
  }

  /* <button> role="button" */
  function onRowKeydown(e: KeyboardEvent, key: string): void {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    e.preventDefault();
    toggleRow(key);
  }

  function detailIdFor(key: string): string {
    return `sidebar-help-change-detail-${key.replace(/[^a-zA-Z0-9]/g, '-')}`;
  }

  function linksFeatures(type: string): boolean {
    return type === 'added' || type === 'changed';
  }

  function onChipClick(e: MouseEvent, id: string): void {
    e.stopPropagation();
    requestFocusFeature(id);
  }

  function openLightbox(src: string, alt: string, caption: string | undefined): void {
    lightbox = { src, alt, caption };
  }

  function closeLightbox(): void {
    lightbox = null;
  }
</script>

{#snippet marked(text: string)}
  {#each highlightSegments(text, tokens, mode) as seg}{#if seg.hit}<mark>{seg.text}</mark>{:else}{seg.text}{/if}{/each}
{/snippet}

<h3 class="sidebar-help__h">{t('sidebar_help.releases.heading')}</h3>

{#if viewState === 'loading'}
  <p class="sidebar-help__note">{t('sidebar_help.releases.loading')}</p>
{:else if viewState === 'failed'}
  <p class="sidebar-help__note sidebar-help__note--error">{t('sidebar_help.releases.failed')}</p>
{:else if viewState === 'unavailable'}
  <p class="sidebar-help__note">{t('sidebar_help.releases.unavailable')}</p>
{:else if releases.length === 0}
  <p class="sidebar-help__note">{t('sidebar_help.releases.empty')}</p>
{:else}
  {#if searching}
    <p class="sidebar-help__note" role="status" data-changelog-count>
      {matchCount === 0
        ? t('info.page.changelog.search.none')
        : t('info.page.changelog.search.count', { count: matchCount })}
      {#if onClearQuery}
        <button type="button" class="oc-btn oc-btn--ghost" data-changelog-clear onclick={onClearQuery}>
          {t('info.page.changelog.search.clear')}
        </button>
      {/if}
    </p>
  {/if}
  <div class="sidebar-help__releases">
    {#each shown as { release, rows }, index (release.name)}
      <section class="sidebar-help__release">
        <button
          type="button"
          class="sidebar-help__release-head"
          aria-expanded={isReleaseOpen(release.name)}
          aria-controls={bodyIdFor(index)}
          onclick={() => toggleRelease(release.name)}
        >
          <span class="sidebar-help__collapse-caret" aria-hidden="true"></span>
          <span class="sidebar-help__release-name">
            {release.isUnreleased ? t('sidebar_help.releases.unreleased') : release.name}
          </span>
          {#if release.date}
            <span class="sidebar-help__release-date">{release.date}</span>
          {/if}
          <span class="sidebar-help__release-counts">
            {#each release.types as group (group.type)}
              <span class="sidebar-help__release-count sidebar-help__release-count--{group.type}">
                <span class="sidebar-help__release-count-n">{group.changes.length}</span>
                {t(`sidebar_help.change_type.${group.type}`)}
              </span>
            {/each}
          </span>
        </button>
        {#if isReleaseOpen(release.name)}
          <ul class="sidebar-help__change-list" id={bodyIdFor(index)}>
            {#each rows as { row, index: i, bodyOnly } (i)}
              {@const key = rowKey(release.name, i)}
              {@const expanded = isRowExpanded(key, bodyOnly)}
              {@const detailId = detailIdFor(key)}
              <li class="sidebar-help__change-item">
                <div
                  class="sidebar-help__change-row"
                  role="button"
                  tabindex="0"
                  aria-expanded={expanded}
                  aria-controls={detailId}
                  onclick={() => toggleRow(key)}
                  onkeydown={(e) => onRowKeydown(e, key)}
                >
                  <span class="sidebar-help__collapse-caret" aria-hidden="true"></span>
                  <span class="sidebar-help__change-type">
                    <span class="sidebar-help__type-chip sidebar-help__type-chip--{row.type}">
                      {t(`sidebar_help.change_type.${row.type}`)}
                    </span>
                  </span>
                  <span class="sidebar-help__change-summary">{@render marked(row.summary)}</span>
                  <span class="sidebar-help__change-features">
                    {#each row.featureLinks as link (link.id)}
                      {#if linksFeatures(row.type)}
                        <button
                          type="button"
                          class="sidebar-help__feature-chip sidebar-help__feature-chip--link"
                          onclick={(e) => onChipClick(e, link.id)}
                        >{@render marked(link.name)}</button>
                      {:else}
                        <span class="sidebar-help__feature-chip">{@render marked(link.name)}</span>
                      {/if}
                    {/each}
                  </span>
                  <span class="sidebar-help__change-pr">{row.pr !== null ? `#${row.pr}` : ''}</span>
                </div>
                {#if expanded}
                  <div class="sidebar-help__change-detail" id={detailId}>
                    <div class="sidebar-help__change-detail-meta">
                      <p class="sidebar-help__change-detail-summary">{@render marked(row.summary)}</p>
                      {#if row.details}
                        <p class="sidebar-help__change-detail-text">{@render marked(row.details)}</p>
                      {/if}
                      <dl class="sidebar-help__change-detail-facts">
                        <div class="sidebar-help__change-detail-fact">
                          <dt>{t('sidebar_help.releases.detail_type')}</dt>
                          <dd>{t(`sidebar_help.change_type.${row.type}`)}</dd>
                        </div>
                        {#if row.date}
                          <div class="sidebar-help__change-detail-fact">
                            <dt>{t('sidebar_help.releases.detail_date')}</dt>
                            <dd>{row.date}</dd>
                          </div>
                        {/if}
                        {#if row.pr !== null}
                          <div class="sidebar-help__change-detail-fact">
                            <dt>{t('sidebar_help.releases.detail_pr')}</dt>
                            <dd>#{row.pr}</dd>
                          </div>
                        {/if}
                        {#if row.issue !== null}
                          <div class="sidebar-help__change-detail-fact">
                            <dt>{t('sidebar_help.releases.detail_issue')}</dt>
                            <dd>#{row.issue}</dd>
                          </div>
                        {/if}
                        {#if row.breaking}
                          <div class="sidebar-help__change-detail-fact sidebar-help__change-detail-fact--breaking">
                            <dt>{t('sidebar_help.releases.detail_breaking')}</dt>
                            <dd>{t('sidebar_help.releases.detail_breaking_yes')}</dd>
                          </div>
                        {/if}
                      </dl>
                    </div>
                    {#each row.featureLinks as link (link.id)}
                      {@const full = catalogById[link.id]}
                      {#if full}
                        {#if linksFeatures(row.type)}
                          <div class="sidebar-help__change-detail-feature">
                            <h5 class="sidebar-help__change-detail-feature-name">{link.name}</h5>
                            <FeatureDetail feature={full} onOpenLightbox={openLightbox} />
                          </div>
                        {:else}
                          <div class="sidebar-help__change-detail-feature sidebar-help__change-detail-feature--brief">
                            <h5 class="sidebar-help__change-detail-feature-name">{link.name}</h5>
                            <p class="sidebar-help__change-detail-feature-summary">{full.summary}</p>
                          </div>
                        {/if}
                      {/if}
                    {/each}
                  </div>
                {/if}
              </li>
            {/each}
          </ul>
        {/if}
      </section>
    {/each}
  </div>
{/if}

{#if lightbox}
  <MediaLightbox src={lightbox.src} alt={lightbox.alt} caption={lightbox.caption} onClose={closeLightbox} />
{/if}
