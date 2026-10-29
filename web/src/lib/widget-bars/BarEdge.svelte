<script lang="ts">
  import type { RailEdge } from '../session-rail/rail-model';

  let { edge, label, place, text, onpress, onkey }: {
    edge: RailEdge;
    label: string;
    place: number;
    text: string;
    onpress: (pos: number, extent: number) => void;
    onkey: (key: string) => boolean;
  } = $props();

  const side = $derived(edge === 'side');

  function onpointerdown(event: PointerEvent): void {
    if (event.button !== 0) return;
    const layer = (event.currentTarget as HTMLElement).parentElement!.getBoundingClientRect();
    onpress(side ? event.clientX : event.clientY, side ? layer.width : layer.height);
    event.preventDefault();
    (event.currentTarget as HTMLElement).focus({ preventScroll: true });
  }

  function onkeydown(event: KeyboardEvent): void {
    if (!onkey(event.key)) return;
    event.preventDefault();
    event.stopPropagation();
  }
</script>


<!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
<div
  class="bar-edge"
  class:bar-edge--side={side}
  class:bar-edge--bottom={!side}
  role="separator"
  tabindex="0"
  aria-orientation={side ? 'vertical' : 'horizontal'}
  aria-label={label}
  aria-valuemin={0}
  aria-valuemax={3}
  aria-valuenow={place}
  aria-valuetext={text}
  data-bar-edge={edge}
  {onpointerdown}
  {onkeydown}
></div>

<style>
  @layer components {
    .bar-edge {
      position: absolute;
      z-index: 2;
      touch-action: none;
      background: transparent;
      outline: none;
    }

    .bar-edge--side {
      top: 0;
      bottom: 0;
      left: 0;
      width: 6px;
      cursor: col-resize;
    }

    .bar-edge--bottom {
      left: 0;
      right: 0;
      top: 0;
      height: 6px;
      cursor: row-resize;
    }

    .bar-edge:hover,
    .bar-edge:focus-visible {
      --_line: var(--oc-text-dim);
    }

    .bar-edge--side:hover,
    .bar-edge--side:focus-visible {
      box-shadow: inset 1px 0 0 0 var(--_line);
    }

    .bar-edge--bottom:hover,
    .bar-edge--bottom:focus-visible {
      box-shadow: inset 0 1px 0 0 var(--_line);
    }
  }
</style>
