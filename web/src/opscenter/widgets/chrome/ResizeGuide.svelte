<script lang="ts">
  import { t } from '../../../lib/i18n/index.svelte';
  import Icon from '../../ui/Icon.svelte';
  import { guideChevrons, type ResizeGuide } from './resize-hint';

  let { guide, message = false }: { guide: ResizeGuide; message?: boolean } = $props();

  const chevrons = $derived(guideChevrons(guide));

  function pinToBody(node: HTMLElement): (() => void) | void {
    const body = node.parentElement;
    if (!body) return;
    const place = (): void => {
      const y = body.scrollTop;
      const x = body.scrollLeft;
      node.style.inset = `${y}px ${-x}px ${-y}px ${x}px`;
    };
    place();
    body.addEventListener('scroll', place, { passive: true });
    return () => body.removeEventListener('scroll', place);
  }
</script>

<div class="oc-resize-guide" data-resize-guide aria-hidden="true" {@attach pinToBody}>
  {#each chevrons as { edge, point } (edge)}
    <span
      class="oc-resize-guide-chevron oc-resize-guide-chevron--{edge}"
      class:oc-resize-guide-chevron--flip={point === 'left'}
      data-resize-edge={edge}
      data-resize-point={point}
      ><Icon name={point === 'up' ? 'chevron-up' : point === 'down' ? 'chevron-down' : 'chevron-right'} size={16} /></span
    >
  {/each}
  {#if message}
    <span class="oc-resize-guide-message" data-resize-hint>{t('widgets.unavailable.resize_to_fit')}</span>
  {/if}
</div>

<style>
  @layer components {
    /* the edit outline */
    .oc-resize-guide {
      position: absolute;
      inset: 0;
      z-index: 50;
      display: grid;
      place-items: center;
      pointer-events: none;
    }

    .oc-resize-guide-chevron {
      position: absolute;
      display: inline-flex;
      color: var(--oc-text-secondary);
    }

    .oc-resize-guide-chevron--top,
    .oc-resize-guide-chevron--bottom {
      inset-inline: 0;
      justify-content: center;
    }

    .oc-resize-guide-chevron--top {
      top: var(--oc-space-1);
    }

    .oc-resize-guide-chevron--bottom {
      bottom: var(--oc-space-1);
    }

    .oc-resize-guide-chevron--left,
    .oc-resize-guide-chevron--right {
      inset-block: 0;
      align-items: center;
    }

    .oc-resize-guide-chevron--left {
      left: var(--oc-space-1);
    }

    .oc-resize-guide-chevron--right {
      right: var(--oc-space-1);
    }

    .oc-resize-guide-chevron--flip :global(svg) {
      transform: rotate(180deg);
    }

    .oc-resize-guide-message {
      padding: var(--oc-space-1) var(--oc-space-2);
      background: var(--oc-ground-field);
      border: var(--oc-border) solid var(--oc-line-rule);
      border-radius: var(--oc-radius-sm);
      color: var(--oc-text-secondary);
      font-family: var(--oc-font);
      font-size: var(--oc-fs-hint);
      white-space: nowrap;
    }

    @media (prefers-reduced-motion: no-preference) {
      .oc-resize-guide-chevron {
        animation: oc-resize-guide-nudge 1.6s ease-in-out infinite;
      }
    }

    @keyframes oc-resize-guide-nudge {
      50% {
        opacity: 0.45;
      }
    }
  }
</style>
