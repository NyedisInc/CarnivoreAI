<script lang="ts">
  import ZoneKeys from '../../lib/zone-shell/ZoneKeys.svelte';
  import { createZone } from '../../lib/zone-shell/zone.svelte';
  import type { KeyFace, TabRef } from '../../lib/zone-shell/zone-types';
  import { GHOST_CHROME } from '../../lib/drag-preview/ghost';
  import { BAR_SIZES, barVars } from '../../lib/widget-bars/bar-size';
  import WidgetIcon from '../../opscenter/ui/WidgetIcon.svelte';

  const metrics = BAR_SIZES.cozy.side;
  const tabsOf = (...keys: string[]): TabRef[] => keys.map((key) => ({ key, kind: 'panel' }));
  const zonesOf = (...groups: string[][]) => groups.map((keys, s) => createZone({
    key: `guide:split:${s}`, tabs: () => tabsOf(...keys), active: () => null, select: () => {}, panel: () => 'closed', strip: 'keys', toolbar: 'none', menuHost: 'bar-key',
  }));
  const face = (tab: TabRef): KeyFace => ({
    title: tab.key, ariaLabel: tab.key, tip: tab.key, label: tab.key, icon: 'file', global: false, chip: false, letter: '', tone: 'oc-text-secondary',
  });

  const STATES = [
    { id: 'slot', zones: zonesOf(['a', 'b', 'c']), cuts: [] as number[], carriedKey: 'b', mark: { section: 0, index: 1 }, ghostAfter: null as number | null, aimed: false },
    { id: 'offer', zones: zonesOf(['a', 'b']), cuts: [] as number[], carriedKey: null, mark: { section: 0, index: 2 }, ghostAfter: 0 as number | null, aimed: false },
    { id: 'aimed', zones: zonesOf(['a', 'b'], ['c']), cuts: [0.5], carriedKey: null, mark: null, ghostAfter: 1 as number | null, aimed: true },
  ];
</script>

<div class="sg-split">
  {#each STATES as state (state.id)}
    <figure class="sg-split__fig">
      <figcaption>{state.id}</figcaption>
      <div class="sg-split__bar" style={barVars('side', 'cozy')} data-bar-size="cozy">
        <ZoneKeys zones={state.zones} axis="y" cuts={state.cuts} ghostAfter={state.ghostAfter} ghostAimed={state.aimed} carriedKey={state.carriedKey}
          labelAt="none" iconPx={metrics.icon} compact={false} editing={true} openKeys={new Set()} {face} mark={state.mark} empty={null}
          onpress={() => {}} onedit={() => {}} ondragstart={() => {}} />
      </div>
    </figure>
  {/each}
  <figure class="sg-split__fig">
    <figcaption>copy</figcaption>
    <span class="sg-split__ghost" style={GHOST_CHROME}><WidgetIcon name="file" widget="core.files" size={metrics.icon} /></span>
  </figure>
</div>

<style>
  .sg-split {
    display: flex;
    flex-wrap: wrap;
    gap: 16px;
    align-items: flex-start;
  }

  .sg-split__fig {
    margin: 0;
    min-width: 0;
  }

  .sg-split__fig figcaption {
    max-width: 150px;
    margin-bottom: 4px;
    font: var(--oc-fs-micro) var(--font-mono);
    letter-spacing: 0.08em;
    color: var(--oc-text-secondary);
  }

  .sg-split__bar {
    display: flex;
    flex-direction: column;
    width: var(--rail-w, 36px);
    height: 220px;
    background: var(--oc-rail-header-ground);
    box-shadow: inset 0 0 0 1px var(--oc-line-frame);
  }

  .sg-split__ghost {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: var(--rail-key-w, 28px);
    height: var(--rail-key-h, 28px);
  }
</style>
