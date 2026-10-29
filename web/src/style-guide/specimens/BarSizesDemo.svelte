<script lang="ts">
  import WidgetIcon from '../../opscenter/ui/WidgetIcon.svelte';
  import { BAR_SIZES, barLabel } from '../../lib/widget-bars/bar-size';
  import { manifestById } from '../../opscenter/widgets/core-manifests';
  import type { BarSize } from '../../lib/widget-bars/bar-settings.svelte';
  import type { RailEdge } from '../../lib/session-rail/rail-model';

  const SIZES: BarSize[] = ['compact', 'cozy', 'detailed'];
  const EDGES: RailEdge[] = ['side', 'bottom'];
  const KEYS = ['core.files', 'core.notes', 'core.tasks'].map((id) => manifestById(id)).filter((m) => m !== undefined);
  const px = (n: number | null): string => (n === null ? 'auto' : `${n}px`);
</script>

<div class="sg-bars">
  {#each SIZES as size (size)}
    {#each EDGES as edge (edge)}
      {@const m = BAR_SIZES[size][edge]}
      <figure class="sg-bars__fig">
        <figcaption>{size} {edge === 'side' ? 'right' : 'bottom'} bar, {m.bar}px</figcaption>
        <div
          class="sg-bars__strip"
          class:sg-bars__strip--side={edge === 'side'}
          style="{edge === 'side' ? 'width' : 'height'}:{m.bar}px;gap:{m.gap}px;padding:{m.pad}px"
        >
          {#each KEYS as manifest (manifest.id)}
            <span
              class="sg-bars__key"
              class:sg-bars__key--under={m.label === 'under'}
              style="width:{px(m.keyW)};height:{px(m.keyH)};min-width:{m.keyMinW}px;min-height:{m.keyMinH}px;padding:{m.keyPad}"
            >
              <WidgetIcon name={manifest.icon} widget={manifest.id} size={m.icon} />
              {#if m.label !== 'none'}<span class="sg-bars__label" style="max-width:{m.label === 'under' ? `${m.labelMaxW}px` : 'none'}">{barLabel(manifest)}</span>{/if}
            </span>
          {/each}
        </div>
      </figure>
    {/each}
  {/each}
</div>

<style>
  .sg-bars {
    display: flex;
    flex-wrap: wrap;
    gap: 16px;
    align-items: flex-start;
  }

  .sg-bars__fig {
    margin: 0;
    min-width: 0;
  }

  .sg-bars__fig figcaption {
    margin-bottom: 4px;
    font: var(--oc-fs-micro) var(--font-mono);
    letter-spacing: 0.08em;
    color: var(--oc-text-secondary);
  }

  .sg-bars__strip {
    display: flex;
    align-items: center;
    box-sizing: border-box;
    background: var(--oc-ground-titlerow);
    box-shadow: inset 0 0 0 1px var(--oc-line-frame);
  }

  .sg-bars__strip--side {
    flex-direction: column;
    align-items: center;
  }

  .sg-bars__key {
    display: inline-flex;
    flex: none;
    align-items: center;
    justify-content: center;
    box-sizing: border-box;
    border-radius: var(--oc-radius-sm);
    color: var(--oc-text-secondary);
  }

  .sg-bars__key--under {
    flex-direction: column;
  }

  .sg-bars__label {
    font-family: var(--font-mono);
    font-size: var(--oc-fs-label);
    line-height: 13px;
    white-space: nowrap;
    margin-left: 6px;
  }

  .sg-bars__key--under .sg-bars__label {
    margin: 3px 0 0;
    font-size: var(--oc-fs-micro);
    line-height: 12px;
    white-space: normal;
    text-align: center;
    text-wrap: balance;
  }
</style>
