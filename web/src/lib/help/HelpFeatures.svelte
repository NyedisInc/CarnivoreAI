
<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { authFetch } from '../../opscenter/api/auth.svelte';
  import { t } from '../i18n/index.svelte';
  import { clearFocusFeature, featureFocusState } from './feature-focus.svelte';
  import {
    findFeature,
    groupFeaturesByArea,
    type FeatureAreaGroup,
    type FeatureCatalogPayload,
  } from './features-by-area';
  import FeatureDetail from './FeatureDetail.svelte';
  import MediaLightbox from './MediaLightbox.svelte';

  type ViewState = 'loading' | 'failed' | 'unavailable' | 'ready';

  let viewState: ViewState = $state('loading');
  let groups: FeatureAreaGroup[] = $state([]);
  let expandedId: string | null = $state(null);
  let lightbox: { src: string; alt: string; caption: string | undefined } | null = $state(null);

  onMount(() => {
    void load();
  });

  async function load(): Promise<void> {
    viewState = 'loading';
    try {
      const payload = await authFetch<FeatureCatalogPayload>('/feature-catalog');
      if (!payload.available) {
        viewState = 'unavailable';
        return;
      }
      groups = groupFeaturesByArea(payload);
      viewState = 'ready';
    } catch {
      viewState = 'failed';
    }
  }

  function isExpanded(id: string): boolean {
    return expandedId === id;
  }

  function toggle(id: string): void {
    expandedId = expandedId === id ? null : id;
  }

  function domIdFor(id: string): string {
    return `sidebar-help-feature-${id}`;
  }

  async function focusFeature(id: string): Promise<void> {
    if (!findFeature(groups, id)) return;
    expandedId = id;
    await tick();
    document.getElementById(domIdFor(id))?.scrollIntoView({ block: 'nearest' });
  }

  $effect(() => {
    const id = featureFocusState.id;
    if (id === null) return;
    void focusFeature(id);
    clearFocusFeature();
  });

  function openLightbox(src: string, alt: string, caption: string | undefined): void {
    lightbox = { src, alt, caption };
  }

  function closeLightbox(): void {
    lightbox = null;
  }
</script>

<h3 class="sidebar-help__h">{t('sidebar_help.features.heading')}</h3>

{#if viewState === 'loading'}
  <p class="sidebar-help__note">{t('sidebar_help.features.loading')}</p>
{:else if viewState === 'failed'}
  <p class="sidebar-help__note sidebar-help__note--error">{t('sidebar_help.features.failed')}</p>
{:else if viewState === 'unavailable'}
  <p class="sidebar-help__note">{t('sidebar_help.features.unavailable')}</p>
{:else if groups.length === 0}
  <p class="sidebar-help__note">{t('sidebar_help.features.empty')}</p>
{:else}
  <div class="sidebar-help__feature-areas">
    {#each groups as group (group.id)}
      <section class="sidebar-help__feature-area">
        <h4 class="sidebar-help__feature-area-name">{group.name}</h4>
        <ul class="sidebar-help__feature-list">
          {#each group.features as feature (feature.id)}
            <li class="sidebar-help__feature" id={domIdFor(feature.id)}>
              <button
                type="button"
                class="sidebar-help__feature-trigger"
                aria-expanded={isExpanded(feature.id)}
                aria-controls="{domIdFor(feature.id)}-body"
                onclick={() => toggle(feature.id)}
              >
                <span class="sidebar-help__collapse-caret" aria-hidden="true"></span>
                <span class="sidebar-help__feature-name">{feature.name}</span>
                <span class="sidebar-help__feature-summary">{feature.summary}</span>
                <span class="sidebar-help__feature-status">
                  {#if feature.status === 'beta' || feature.status === 'deprecated'}
                    <span class="sidebar-help__feature-badge sidebar-help__feature-badge--{feature.status}">
                      {t(`sidebar_help.features.status.${feature.status}`)}
                    </span>
                  {/if}
                </span>
              </button>
              <div
                class="sidebar-help__feature-body"
                id="{domIdFor(feature.id)}-body"
                hidden={!isExpanded(feature.id)}
              >
                {#if isExpanded(feature.id)}
                  <FeatureDetail {feature} onOpenLightbox={openLightbox} />
                {/if}
              </div>
            </li>
          {/each}
        </ul>
      </section>
    {/each}
  </div>
{/if}

{#if lightbox}
  <MediaLightbox src={lightbox.src} alt={lightbox.alt} caption={lightbox.caption} onClose={closeLightbox} />
{/if}
