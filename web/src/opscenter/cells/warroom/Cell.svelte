<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';
  import { WARROOM_STATE } from './state';

  const PEEK_STOPS = [0, 25, 50, 75, 100] as const;

  export const WARROOM_WIDGET = defineWidget({
    id: 'core.warroom',
    scope: 'global',
    actions: [
      { id: 'show-shells', labelKey: 'warroom.toggle.shells', kind: 'switch', group: 'show' },
      { id: 'show-browsers', labelKey: 'warroom.toggle.browsers', kind: 'switch', group: 'show' },
      { id: 'show-sleeping', labelKey: 'warroom.toggle.asleep', kind: 'switch', group: 'show' },
      { id: 'show-computers', labelKey: 'warroom.toggle.computers', kind: 'switch', group: 'show' },
      ...PEEK_STOPS.map((stop) => ({ id: `peek:${stop}`, labelKey: `warroom.peek_zoom.stop_${stop}`, kind: 'choice' as const, group: 'peek' })),
    ],
    state: WARROOM_STATE,
  });
</script>

<script lang="ts">
  import type { CellProps } from '../../lib/cell';
  import { t } from '../../../lib/i18n/index.svelte';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import ShellScroll from '../../widgets/shell/ShellScroll.svelte';
  import { useWidget, type WidgetHandle } from '../../widgets/shell/define-widget.svelte';
  import WarroomWall from '../../../lib/warroom/WarroomWall.svelte';
  import { wallGroups, wallLoaded } from '../../../lib/warroom/wall-data.svelte';
  import { peekPosition, peekStored, type PeekRange } from '../../../lib/warroom/wall-layout';

  let props: CellProps = $props();

  const widget: WidgetHandle<typeof WARROOM_WIDGET> = useWidget(WARROOM_WIDGET, () => props, () => ({
    'show-shells': { on: view.shells, run: () => (view.shells = !view.shells) },
    'show-browsers': { on: view.browsers, run: () => (view.browsers = !view.browsers) },
    'show-sleeping': { on: view.asleep, run: () => (view.asleep = !view.asleep) },
    'show-computers': { on: view.computers, run: () => (view.computers = !view.computers) },
    ...Object.fromEntries(PEEK_STOPS.map((stop) => [`peek:${stop}`, { on: position === stop, run: () => setPosition(stop) }])),
  }));
  const view = widget.state;

  let range = $state<PeekRange>({ ref: 0, low: 0, high: 0 });
  const position = $derived(peekPosition(view.peekwidth, range));
  const usable = $derived(range.high > range.low);
  function setPosition(p: number): void {
    if (usable) view.peekwidth = peekStored(p, range);
  }

  const groups = $derived(wallGroups({ shells: view.shells, browsers: view.browsers, asleep: view.asleep, computers: view.computers }));
  const status = $derived(!wallLoaded() ? 'loading' : groups.length === 0 ? 'empty' : 'ready');

  const chips = $derived([
    { name: 'shells', label: t('warroom.toggle.shells'), on: view.shells, flip: () => (view.shells = !view.shells) },
    { name: 'browsers', label: t('warroom.toggle.browsers'), on: view.browsers, flip: () => (view.browsers = !view.browsers) },
    { name: 'asleep', label: t('warroom.toggle.asleep'), on: view.asleep, flip: () => (view.asleep = !view.asleep) },
    { name: 'computers', label: t('warroom.toggle.computers'), on: view.computers, flip: () => (view.computers = !view.computers) },
  ]);
</script>

{#snippet controls(place: 'header' | 'body' | 'corner')}
  {#if place !== 'corner'}
    {#each chips as chip (chip.name)}
      <button type="button" class="oc-chip" data-wr-toggle={chip.name} aria-pressed={chip.on} onclick={chip.flip}>{chip.label}</button>
    {/each}
    <label class="ww-peek">
      <span class="ww-peek-label">{t('warroom.peek_zoom')}</span>
      <input class="ww-peek-range" type="range" min="0" max="100" step="1" data-wr-peek value={position} disabled={!usable} oninput={(event) => setPosition(Number(event.currentTarget.value))} />
      <span class="ww-peek-val">{position}</span>
    </label>
  {/if}
{/snippet}

<WidgetShell {widget} {status} note={status === 'empty' ? t('warroom.empty') : ''} {controls}>
  <ShellScroll>
    <WarroomWall {groups} peekWidth={view.peekwidth} bind:range />
  </ShellScroll>
</WidgetShell>
