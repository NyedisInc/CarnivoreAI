<script lang="ts">
  import Icon from '../../opscenter/ui/Icon.svelte';
  import IconButton from '../base/IconButton.svelte';
  import { t } from '../i18n/index.svelte';
  import { widgetBars, type PinEdge } from './bar-settings.svelte';
  import { BAR_SIZES, RAIL_PIN_BOX_PX, RAIL_PIN_GLYPH_PX } from './bar-size';
  import { barPinned, stripPinsOffered, toggleBarPin } from './bar-pin-action';

  let { edge }: { edge: PinEdge } = $props();

  const pinned = $derived(barPinned(edge));
  const size = $derived(edge === 'rail' ? 'cozy' : widgetBars.view[edge].size);
  const box = $derived(edge === 'rail' ? RAIL_PIN_BOX_PX : Math.min(BAR_SIZES[size][edge].keyW ?? 28, 28));
  const glyph = $derived(edge === 'rail' ? RAIL_PIN_GLYPH_PX : BAR_SIZES[size][edge].icon);
  const label = $derived(t(`${edge === 'rail' ? 'sidebar.rail.menu' : 'widget_bars.menu'}.${pinned ? 'unpin' : 'pin'}`));
</script>

{#if stripPinsOffered()}
<IconButton {label} variant="quiet" pressed={pinned} data-bar-pin style={`--oc-ibtn-size: ${box}px`}
  onclick={() => void toggleBarPin(edge)}><Icon name="bar-pin" size={glyph} strokeWidth={2} /></IconButton>
{/if}

<style>
  @layer components {
    :global([data-bar-pin]) {
      flex: none;
      color: var(--oc-text-muted);
    }

    :global([data-bar-pin]:hover:not(:disabled)),
    :global([data-bar-pin][aria-pressed='true']) {
      color: var(--oc-text-bright);
    }

    :global([data-bar-pin]:not([aria-pressed='true']) svg) {
      transform: rotate(45deg);
    }
  }
</style>
