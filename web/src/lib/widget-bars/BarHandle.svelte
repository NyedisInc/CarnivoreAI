<script lang="ts">
  import GripPill from '../grip/GripPill.svelte';
  import { t } from '../i18n/index.svelte';
  import type { PinEdge } from './bar-settings.svelte';

  let { edge, expanded = false, controls, label, tone, onpress, ondrag, swallowClick }: {
    edge: PinEdge;
    expanded?: boolean;
    label?: string;
    tone?: 'question';
    controls?: string;
    onpress?: (kind: 'keyboard' | 'touch' | 'pointer') => void;
    ondrag?: (pos: number) => void;
    swallowClick?: () => boolean;
  } = $props();

  const LABELS: Record<PinEdge, string> = {
    side: 'widget_bars.handle.side',
    bottom: 'widget_bars.handle.bottom',
    rail: 'sidebar.rail.handle',
  };

  let lastType = 'mouse';
</script>

<button
  type="button"
  class="bar-handle"
  class:bar-handle--side={edge === 'side'}
  class:bar-handle--bottom={edge === 'bottom'}
  class:bar-handle--rail={edge === 'rail'}
  data-bar-handle
  data-tone={tone}
  aria-label={label ?? t(LABELS[edge])}
  aria-expanded={expanded}
  aria-controls={controls}
  onpointerdown={(event) => {
    lastType = event.pointerType;
    if (event.button === 0) ondrag?.(edge === 'side' ? event.clientX : event.clientY);
  }}
  onclick={(event) => swallowClick?.() || onpress?.(event.detail === 0 ? 'keyboard' : lastType === 'touch' ? 'touch' : 'pointer')}
><GripPill axis={edge === 'bottom' ? 'x' : 'y'} /></button>

<style>
  @layer components {
    .bar-handle {
      --_bd: var(--oc-line-frame);
      position: relative;
      display: flex;
      align-items: center;
      justify-content: center;
      box-sizing: border-box;
      width: 100%;
      height: 100%;
      margin: 0;
      padding: 0;
      border: var(--oc-border) solid transparent;
      border-radius: 0;
      background: var(--oc-rail-header-ground);
      color: var(--oc-text-dim);
      cursor: pointer;
      touch-action: none;
    }

    .bar-handle--side {
      box-shadow: inset 1px 0 0 0 var(--oc-line-frame);
    }

    .bar-handle--rail {
      box-shadow: inset -1px 0 0 0 var(--oc-line-frame);
    }

    .bar-handle--rail[aria-expanded='false'] {
      background: linear-gradient(to bottom, color-mix(in oklab, var(--oc-orange) 30%, var(--oc-rail-header-ground)), var(--oc-rail-header-ground));
      --grip-color: var(--oc-text-dim);
    }

    .bar-handle--rail[aria-expanded='false'][data-tone='question'] {
      background: linear-gradient(to bottom, color-mix(in oklab, var(--oc-yellow) 30%, var(--oc-rail-header-ground)), var(--oc-rail-header-ground));
    }

    .bar-handle--bottom {
      box-shadow: inset 0 1px 0 0 var(--oc-line-frame);
    }

    .bar-handle:hover {
      --grip-color: var(--oc-text-dim);
    }

    @media (pointer: coarse) {
      .bar-handle::before {
        content: '';
        position: absolute;
        background: transparent;
      }

      .bar-handle--side::before {
        top: 0;
        bottom: 0;
        right: 0;
        width: 24px;
      }

      .bar-handle--rail::before {
        top: 0;
        bottom: 0;
        left: 0;
        width: 24px;
      }

      .bar-handle--bottom::before {
        left: 0;
        right: 0;
        bottom: 0;
        height: 24px;
      }
    }
  }
</style>
