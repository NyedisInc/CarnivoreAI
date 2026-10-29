
<script lang="ts">
  import { onDestroy, untrack } from 'svelte';
  import { t } from '../i18n/index.svelte';
  import { Button } from '../base';
  import { fetchFeatureMediaBlob } from './feature-media';
  import type { FeatureMediaItem } from './features-by-area';

  interface Props {
    featureId: string;
    item: FeatureMediaItem;
    onOpen: (url: string, alt: string, caption: string | undefined) => void;
  }

  const { featureId, item, onOpen }: Props = $props();

  let objectUrl: string | null = $state(null);
  let loadFailed: boolean = $state(false);
  let playing: boolean = $state(untrack(() => item.kind !== 'gif'));

  function revoke(): void {
    if (objectUrl) {
      URL.revokeObjectURL(objectUrl);
      objectUrl = null;
    }
  }

  onDestroy(revoke);

  async function load(): Promise<void> {
    if (objectUrl || loadFailed) return;
    try {
      const blob = await fetchFeatureMediaBlob(featureId, item.file);
      objectUrl = URL.createObjectURL(blob);
    } catch {
      loadFailed = true;
    }
  }

  $effect(() => {
    if (playing) void load();
  });

  function play(): void {
    playing = true;
  }
</script>

{#if item.kind === 'gif' && !playing}
  <Button
    variant="row"
    data-help-media-tile
    data-help-media-gif-poster
    onclick={play}
    onfocus={play}
    aria-label={t('sidebar_help.features.gif_play', { alt: item.alt })}
  >
    <span class="sidebar-help__media-gif-play" aria-hidden="true">&#9654;</span>
    {#if item.caption}<span class="sidebar-help__media-caption">{item.caption}</span>{/if}
  </Button>
{:else if loadFailed}
  <div class="sidebar-help__media-item sidebar-help__media-item--failed">
    <span class="sidebar-help__media-caption">{item.alt}</span>
  </div>
{:else if objectUrl}
  <Button
    variant="row"
    data-help-media-tile
    onclick={() => onOpen(objectUrl as string, item.alt, item.caption)}
  >
    <img src={objectUrl} alt={item.alt} loading="lazy" class="sidebar-help__media-img" />
    {#if item.caption}<span class="sidebar-help__media-caption">{item.caption}</span>{/if}
    {#if item.state}<span class="sidebar-help__media-state">{item.state}</span>{/if}
  </Button>
{:else}
  <div class="sidebar-help__media-item sidebar-help__media-item--loading" aria-hidden="true"></div>
{/if}
