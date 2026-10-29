<script lang="ts">
  import { onDestroy } from 'svelte';
  import WidgetIcon from '../ui/WidgetIcon.svelte';
  import { fetchFeatureMediaBlob } from '../../lib/help/feature-media';
  import type { WidgetManifest } from '../widgets/types';
  import { authFetchBlob } from '../../opscenter/api/auth.svelte';
  import { pluginPreviewFor, thumbnailFor } from './thumbnails';

  let { manifest, wide = false }: { manifest: WidgetManifest; wide?: boolean } = $props();

  let url = $state<string | null>(null);

  $effect(() => {
    const preview = pluginPreviewFor(manifest.id);
    const source = thumbnailFor(manifest.id);
    if (!preview && !source) return;
    let live = true;
    (preview ? authFetchBlob(preview) : fetchFeatureMediaBlob(source!.feature, source!.file))
      .then((blob) => {
        if (!live || typeof URL.createObjectURL !== 'function') return;
        url = URL.createObjectURL(blob);
      })
      .catch((error: unknown) => {
        console.warn('[layout-editor] thumbnail unavailable', manifest.id, error);
      });
    return () => {
      live = false;
    };
  });

  onDestroy(() => {
    if (url) URL.revokeObjectURL(url);
  });

  const steps = $derived(manifest.densities.width.length);
</script>

<span class="le-thumb" class:le-thumb--wide={wide} data-thumb={url ? 'media' : 'placeholder'} aria-hidden="true">
  {#if url}
    <img class="le-thumb__img" src={url} alt="" draggable="false" />
  {:else}
    <span class="le-thumb__icon" style={`color: var(--${manifest.iconTone})`}>
      <WidgetIcon name={manifest.icon} widget={manifest.id} size={20} />
    </span>
    <span class="le-thumb__steps">
      {#each { length: steps } as _, at (at)}
        <span class="le-thumb__step" style={`width: ${10 + at * 6}px`}></span>
      {/each}
    </span>
  {/if}
</span>

<style>
  @layer components {
    .le-thumb {
      position: relative;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 6px;
      flex: 0 0 auto;
      width: 76px;
      height: 52px;
      overflow: hidden;
      background: var(--oc-ground-raised);
      border: var(--oc-border, 1px) solid var(--oc-line-faint);
      border-radius: var(--oc-radius-sm, 2px);
    }

    .le-thumb--wide {
      width: 100%;
      height: 132px;
    }

    .le-thumb__img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      object-position: top left;
    }

    .le-thumb__icon {
      display: inline-flex;
    }

    .le-thumb__steps {
      display: flex;
      align-items: flex-end;
      gap: 2px;
    }

    .le-thumb__step {
      display: block;
      height: 2px;
      background: var(--oc-line-rule);
    }
  }
</style>
