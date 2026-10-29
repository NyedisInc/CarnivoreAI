<script lang="ts">
  import type { Layout, SlotId } from '../../opscenter/engine/types';
  import { slotTitle } from '../../opscenter/layout-editor/editor.svelte';
  import { boardShape } from './board-shape';
  import { t } from '../i18n/index.svelte';

  let { layout, home = false }: { layout: Layout | undefined; home?: boolean } = $props();

  const shape = $derived(boardShape(layout));

  function nameOf(id: SlotId): string {
    try {
      return slotTitle(id);
    } catch (error) {
      if (error instanceof Error) return '';
      throw error;
    }
  }
</script>

<div class="oc-well dash-preview" class:dash-preview--home={home} aria-hidden="true" data-dashboard-preview={shape.widgets}>
  {#each shape.boxes as box (box.id)}
    <span
      class="dash-preview__box"
      style={`left: ${box.left}%; top: ${box.top}%; width: ${box.width}%; height: ${box.height}%`}
      ><span class="dash-preview__name">{nameOf(box.id)}</span></span
    >
  {:else}
    <span class="dash-preview__empty">{t('dashboards.preview_empty')}</span>
  {/each}
</div>

<style>
  @layer components {
    .dash-preview {
      position: relative;
      display: block;
      width: 100%;
      aspect-ratio: 16 / 9;
      overflow: hidden;
      padding: 0;
      background: var(--oc-ground-content, var(--oc-ground-page));
    }

    .dash-preview__box {
      position: absolute;
      box-sizing: border-box;
      display: flex;
      align-items: flex-start;
      padding: 3px 4px;
      border: 2px solid transparent;
      background-clip: padding-box;
      background-color: var(--oc-ground-raised);
      box-shadow: inset 0 0 0 1px var(--oc-line-faint);
      overflow: hidden;
    }

    .dash-preview--home .dash-preview__box {
      background-color: color-mix(in srgb, var(--oc-green) 8%, var(--oc-ground-raised));
      box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--oc-green) 35%, var(--oc-line-faint));
    }

    .dash-preview__name {
      min-width: 0;
      overflow: hidden;
      font-size: 9px;
      line-height: 1.2;
      letter-spacing: var(--oc-tracking-label, 0.6px);
      text-transform: uppercase;
      text-overflow: ellipsis;
      white-space: nowrap;
      color: var(--oc-text-muted);
    }

    .dash-preview__empty {
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: var(--oc-fs-label);
      color: var(--oc-text-muted);
    }
  }
</style>
