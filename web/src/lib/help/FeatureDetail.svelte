
<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import type { FeatureCatalogItem, FeatureMediaItem } from './features-by-area';
  import FeatureMedia from './FeatureMedia.svelte';

  interface Props {
    feature: FeatureCatalogItem;
    onOpenLightbox: (src: string, alt: string, caption: string | undefined) => void;
  }

  const { feature, onOpenLightbox }: Props = $props();

  const hasMedia = $derived((feature.media?.length ?? 0) > 0 || Boolean(feature.media_exempt));

  function iconMedia(f: FeatureCatalogItem): FeatureMediaItem[] {
    return (f.media ?? []).filter((m) => m.kind === 'icon');
  }

  function otherMedia(f: FeatureCatalogItem): FeatureMediaItem[] {
    return (f.media ?? []).filter((m) => m.kind !== 'icon');
  }
</script>

<div class="sidebar-help__feature-detail" data-has-media={hasMedia}>
  <div class="sidebar-help__feature-text">
    {#if feature.where?.length}
      <div class="sidebar-help__feature-section">
        <div class="sidebar-help__feature-section-label">
          {t('sidebar_help.features.where')}
        </div>
        <ul class="sidebar-help__feature-plain-list">
          {#each feature.where as line, i (i)}<li>{line}</li>{/each}
        </ul>
      </div>
    {/if}
    {#if feature.how_to?.length}
      <div class="sidebar-help__feature-section">
        <div class="sidebar-help__feature-section-label">
          {t('sidebar_help.features.how_to')}
        </div>
        <ol class="sidebar-help__feature-steps">
          {#each feature.how_to as step, i (i)}<li>{step}</li>{/each}
        </ol>
      </div>
    {/if}
    {#if feature.examples?.length}
      <div class="sidebar-help__feature-section">
        <div class="sidebar-help__feature-section-label">
          {t('sidebar_help.features.examples')}
        </div>
        <ul class="sidebar-help__feature-plain-list">
          {#each feature.examples as example, i (i)}<li>{example}</li>{/each}
        </ul>
      </div>
    {/if}
  </div>
  {#if feature.media?.length}
    <div class="sidebar-help__feature-media-col">
      <div class="sidebar-help__feature-section-label">
        {t('sidebar_help.features.media')}
      </div>
      {#if iconMedia(feature).length}
        <div class="sidebar-help__media-row">
          {#each iconMedia(feature) as item, i (i)}
            <FeatureMedia featureId={feature.id} {item} onOpen={onOpenLightbox} />
          {/each}
        </div>
      {/if}
      {#if otherMedia(feature).length}
        <div class="sidebar-help__media-row sidebar-help__media-row--large">
          {#each otherMedia(feature) as item, i (i)}
            <FeatureMedia featureId={feature.id} {item} onOpen={onOpenLightbox} />
          {/each}
        </div>
      {/if}
    </div>
  {:else if feature.media_exempt}
    <div class="sidebar-help__feature-media-col">
      <div class="sidebar-help__feature-section-label">
        {t('sidebar_help.features.media')}
      </div>
      <p class="sidebar-help__note">{feature.media_exempt}</p>
    </div>
  {/if}
</div>
