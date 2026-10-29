<script lang="ts">
  import BoardPreview from '../dashboards/BoardPreview.svelte';
  import type { Layout } from '../../opscenter/engine/types';
  import { t } from '../i18n/index.svelte';

  let { anchor, layout, name, home = false }: { anchor: HTMLElement | null; layout: Layout | undefined; name: string; home?: boolean } = $props();

  const WIDTH = 220;
  const GAP = 8;

  let card = $state<HTMLElement | null>(null);
  let box = $state({ left: 0, top: 0 });

  function place(): void {
    if (!anchor || typeof window === 'undefined') return;
    const rect = anchor.getBoundingClientRect();
    const height = card?.offsetHeight ?? 0;
    const right = rect.right + GAP;
    const left = right + WIDTH + GAP <= window.innerWidth ? right : Math.max(GAP, rect.left - WIDTH - GAP);
    box = { left, top: Math.max(GAP, Math.min(rect.top, window.innerHeight - height - GAP)) };
  }

  $effect(() => {
    place();
    if (card && !card.matches(':popover-open')) card.showPopover();
  });
</script>

<div
  bind:this={card}
  class="mnu-preview popup-focus"
  popover="manual"
  aria-hidden="true"
  data-menu-preview={name}
  style={`left: ${Math.round(box.left)}px; top: ${Math.round(box.top)}px; width: ${WIDTH}px`}
>
  <span class="mnu-preview__name">{name}{#if home}<span class="mnu-preview__home">{t('dashboards.active_badge')}</span>{/if}</span>
  <BoardPreview {layout} {home} />
</div>

<style>
  @layer components {
    .mnu-preview {
      position: fixed;
      inset: auto;
      margin: 0;
      display: grid;
      gap: var(--oc-space-1);
      padding: var(--oc-space-2);
      background: var(--oc-ground-panel);
      border: var(--oc-border) solid var(--oc-line-frame);
      border-radius: var(--oc-radius-sm);
      pointer-events: none;
    }

    .mnu-preview__name {
      display: flex;
      align-items: center;
      gap: var(--oc-space-2);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-label);
      letter-spacing: var(--oc-tracking-label);
      text-transform: uppercase;
      color: var(--oc-text-secondary);
    }

    .mnu-preview__home {
      color: var(--oc-green);
    }
  }
</style>
