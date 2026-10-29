<script lang="ts">
  import { untrack } from 'svelte';
  import IconButton from '../base/IconButton.svelte';
  import { resolvePlacement } from '../../opscenter/widgets/placement-resolve';
  import GlanceOptionsOverlay from './GlanceOptionsOverlay.svelte';
  import { t } from '../i18n/index.svelte';
  import { glanceFor } from './glance';
  import { glanceDrag, beginGlancePlacementDrag } from './glance-drag.svelte';
  import GlanceTiles from './GlanceTiles.svelte';
  import { drawerZone } from './zone-store.svelte';

  let { onopen }: { onopen: () => void } = $props();

  const drawn = $derived(
    drawerZone.glance.flatMap((placement) => {
      const resolved = resolvePlacement({ widget: placement.widget });
      return resolved ? [{ placement, manifest: resolved.manifest }] : [];
    }),
  );

  let optionsFor = $state<string | null>(null);
  let anchor = $state<HTMLElement | null>(null);

  function showOptions(id: string, event: MouseEvent): void {
    anchor = (event.currentTarget as HTMLElement).closest<HTMLElement>('[data-glance-place]');
    optionsFor = id;
  }

  function closeOptions(): void {
    optionsFor = null;
  }

  function onHandleDown(event: PointerEvent, id: string): void {
    beginGlancePlacementDrag(event.currentTarget as HTMLElement, event, id, {
      onDrop: (to) => drawerZone.moveGlance(id, to),
    });
  }

  function onHandleKey(event: KeyboardEvent, id: string, index: number): void {
    const step = event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -1 : event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 1 : 0;
    if (step === 0) return;
    event.preventDefault();
    const to = index + step;
    if (to < 0 || to >= untrack(() => drawn.length)) return;
    drawerZone.moveGlance(id, to);
  }

  function remove(id: string): void {
    if (optionsFor === id) optionsFor = null;
    drawerZone.removeGlance(id);
  }
</script>

<div
  class="dz-garea"
  class:dz-garea--open={glanceDrag.carrying}
  class:dz-garea--aimed={glanceDrag.index !== null}
  data-glance-area
  data-drop={glanceDrag.index !== null ? 'aimed' : glanceDrag.carrying ? 'open' : undefined}
  role="group"
  aria-label={t('drawer_zone.glance_area.label')}
>
  {#each drawn as entry, i (entry.placement.id)}
    {@const title = t(entry.manifest.titleKey)}
    {@const declares = !!glanceFor(entry.placement.widget)?.options}
    {#if glanceDrag.index === i}<div class="dz-gmark" data-glance-mark></div>{/if}
    <div class="dz-gplace" data-glance-place={entry.placement.id} data-glance-widget={entry.placement.widget}>
      <div class="dz-gtiles">
        <GlanceTiles
          placement={entry.placement.id}
          widget={entry.placement.widget}
          manifest={entry.manifest}
          options={entry.placement.options}
          {onopen}
        />
      </div>
      <div class="dz-gctl" role="group" aria-label={title}>
        <IconButton label={t('drawer_zone.glance_area.move', { title })} variant="quiet" icon="grip" iconSize={11} data-glance-handle
          onpointerdown={(event) => onHandleDown(event, entry.placement.id)}
          onkeydown={(event) => onHandleKey(event, entry.placement.id, i)} />
        {#if declares}
          <IconButton label={t('drawer_zone.glance_area.options', { title })} variant="quiet" icon="settings" iconSize={11}
            data-glance-options aria-expanded={optionsFor === entry.placement.id}
            onclick={(event) => showOptions(entry.placement.id, event)} />
        {/if}
        <IconButton label={t('drawer_zone.glance_area.remove', { title })} variant="close" data-glance-remove
          onclick={() => remove(entry.placement.id)}>&#215;</IconButton>
      </div>
    </div>
  {/each}
  {#if glanceDrag.index !== null && glanceDrag.index >= drawn.length}<div class="dz-gmark" data-glance-mark></div>{/if}
</div>

{#if optionsFor}
  <GlanceOptionsOverlay placement={optionsFor} {anchor} onClose={closeOptions} />
{/if}

<style>
  @layer components {
    /* a wrapping row */
    .dz-garea {
      position: relative;
      display: flex;
      flex-wrap: wrap;
      align-items: flex-start;
      gap: var(--oc-space-1);
      min-height: 44px;
      margin-top: var(--oc-space-1);
      padding: var(--oc-space-1) var(--oc-space-2);
      box-sizing: border-box;
    }

    .dz-garea::after {
      content: '';
      position: absolute;
      inset: 0;
      z-index: 60;
      border: var(--oc-border) dashed var(--oc-yellow);
      pointer-events: none;
    }

    .dz-garea--open {
      background: color-mix(in oklab, var(--oc-yellow) 6%, transparent);
    }

    .dz-garea--aimed {
      background: color-mix(in oklab, var(--oc-yellow) 12%, transparent);
    }

    .dz-garea--aimed::after {
      border-style: solid;
    }

    .dz-gplace {
      display: grid;
      gap: calc(var(--oc-space-1) / 2);
      justify-items: start;
    }

    .dz-gtiles {
      display: flex;
      gap: var(--oc-space-1);
    }

    .dz-gctl {
      display: flex;
      gap: calc(var(--oc-space-1) / 2);
      color: var(--oc-text-secondary);
    }

    .dz-gctl {
      --oc-ibtn-size: 16px;
    }

    .dz-gctl :global([data-glance-handle]) {
      cursor: grab;
      touch-action: none;
    }

    .dz-gmark {
      align-self: stretch;
      width: 2px;
      min-height: 36px;
      background: var(--oc-orange);
    }
  }
</style>
