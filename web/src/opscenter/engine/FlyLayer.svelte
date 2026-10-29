<script module lang="ts">
  /*  hidden  */
  import { tick } from 'svelte';
  import { META, metaFor } from './meta';
  import { anchorRect, navAnchors } from './navAnchors.svelte';
  import { flipCells, measureCells } from './flip';
  import type { LayoutStore } from './layout.svelte';
  import type { ArrangeMode } from './model';
  import { reducedMotion } from './viewport.svelte';
  import type { SlotId } from './types';
  import { t } from '../../lib/i18n/index.svelte';

  export interface Flight {
    icon: string;
    tone: string;
    from: DOMRect;
    to: DOMRect;
  }

  const FLIGHT = 320;

  let launch: ((flight: Flight) => Promise<void>) | null = null;

  export function registerFlyLayer(fn: (flight: Flight) => Promise<void>): () => void {
    launch = fn;
    return () => {
      if (launch === fn) launch = null;
    };
  }

  export async function flyIcon(flight: Flight): Promise<void> {
    if (!launch || reducedMotion()) return;
    await launch(flight);
  }

  function cornerOf(id: SlotId): HTMLElement | null {
    return document.querySelector<HTMLElement>(`[data-cell="${id}"] [data-corner]`);
  }

  function titleOf(id: SlotId): string {
    const meta = metaFor(id, META);
    return meta.titleName ?? t(meta.titleKey);
  }

  export async function hideWithFlight(store: LayoutStore, id: SlotId, from: DOMRect | null): Promise<void> {
    const meta = metaFor(id, META);
    const to = anchorRect('components');
    const before = measureCells();
    store.hide(id);
    await tick();
    flipCells(before);
    store.announce(t('opscenter.layout.cell_hidden', { title: t(meta.titleKey) }));
    if (from && to) await flyIcon({ icon: meta.icon, tone: meta.iconTone, from, to });
    navAnchors.components?.focus();
  }

  /*  hidden  */
  export async function restoreWithFlight(store: LayoutStore, id: SlotId): Promise<void> {
    const meta = metaFor(id, META);
    const from = anchorRect('components');
    const before = measureCells();
    store.show(id);
    await tick();
    flipCells(before);
    store.announce(t('opscenter.layout.cell_restored', { title: t(meta.titleKey) }));
    const corner = cornerOf(id);
    const to = corner ? corner.getBoundingClientRect() : null;
    if (from && to) await flyIcon({ icon: meta.icon, tone: meta.iconTone, from, to });
    corner?.focus();
  }

  export async function removeWithReflow(store: LayoutStore, id: SlotId): Promise<void> {
    const title = titleOf(id);
    const before = measureCells();
    store.remove(id);
    await tick();
    flipCells(before);
    store.announce(t('opscenter.layout.cell_removed', { title }));
    navAnchors.components?.focus();
  }

  export async function arrangeWithReflow(store: LayoutStore, mode: ArrangeMode): Promise<void> {
    const before = measureCells();
    store.arrange(mode);
    await tick();
    flipCells(before);
    store.announce(t(`opscenter.layout.arranged_${mode}`));
  }
</script>

<script lang="ts">
  import Icon from '../ui/Icon.svelte';

  interface Live extends Flight {
    key: number;
  }

  let live = $state<Live[]>([]);
  let next = 0;

  function run(flight: Flight): Promise<void> {
    const key = (next += 1);
    live = [...live, { ...flight, key }];
    return tick().then(() => {
      const element = document.querySelector<HTMLElement>(`[data-flight="${key}"]`);
      if (!element) {
        live = live.filter((entry) => entry.key !== key);
        return;
      }
      const dx = flight.to.x + flight.to.width / 2 - (flight.from.x + flight.from.width / 2);
      const dy = flight.to.y + flight.to.height / 2 - (flight.from.y + flight.from.height / 2);
      const animation = element.animate(
        [
          { transform: 'translate(0px, 0px) scale(1)', opacity: 1 },
          { transform: `translate(${dx / 2}px, ${dy / 2 - 46}px) scale(0.82)`, opacity: 0.9, offset: 0.5 },
          { transform: `translate(${dx}px, ${dy}px) scale(0.6)`, opacity: 0.25 },
        ],
        { duration: FLIGHT, easing: 'cubic-bezier(.4,0,.2,1)', fill: 'forwards' },
      );
      return animation.finished
        .catch(() => undefined)
        .then(() => {
          live = live.filter((entry) => entry.key !== key);
        });
    });
  }

  $effect(() => registerFlyLayer(run));
</script>

<div class="oc-fly" aria-hidden="true">
  {#each live as flight (flight.key)}
    <span
      class="oc-fly-icon"
      data-flight={flight.key}
      style={`left: ${flight.from.x}px; top: ${flight.from.y}px; width: ${flight.from.width}px; height: ${flight.from.height}px; color: var(--${flight.tone})`}
    >
      <Icon name={flight.icon} size={15} />
    </span>
  {/each}
</div>

<style>
  @layer components {
    .oc-fly {
      position: fixed;
      inset: 0;
      pointer-events: none;
      z-index: 60;
    }

    .oc-fly-icon {
      position: absolute;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      will-change: transform, opacity;
    }
  }
</style>
