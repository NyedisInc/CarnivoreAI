<script lang="ts">
  import CellFrame from './shell/CellFrame.svelte';
  import { entryFor } from './cells/registry';
  import { isPluginSlot, panels } from './engine/plugin-kinds';
  import { sizeOf } from './engine/observe.svelte';
  import { pickState } from './lib/states';
  import { META, metaFor, kindOf } from './engine/meta';
  import TerminalGroupCell from './cells/terminal-group/Cell.svelte';
  import type { CellMeta, SlotId } from './engine/types';
  import type { LayoutStore } from './engine/layout.svelte';
  import { viewport } from './engine/viewport.svelte';
  import { t } from '../lib/i18n/index.svelte';
  import { declareWidgetActions } from './widgets/menu/declared-actions.svelte';
  import { manifestById } from './widgets/core-manifests';
  import { activeScopeFor } from './widgets/active-scope';
  import { gridHeaderId } from './shell/grid-zone';

  let { id, store }: { id: SlotId; store: LayoutStore } = $props();

  const entry = $derived((panels().revision(), entryFor(id)));

  const meta = $derived<CellMeta>((panels().revision(), metaFor(id, META)));

  const RIGHT_CONTROL_KEYS: Readonly<Record<string, string>> = {
    'view-all': 'opscenter.frame.view_all',
    refresh: 'opscenter.frame.refresh',
    clear: 'opscenter.frame.clear',
  };

  $effect(() => {
    const run = entry?.onRightControl;
    const key = meta.rightControl ? RIGHT_CONTROL_KEYS[meta.rightControl] : undefined;
    if (!run || !key) return;
    return declareWidgetActions(gridHeaderId(id), 'frame', [{ id: meta.rightControl!, label: t(key), run }]);
  });

  const instance = $derived(id);
  const box = $derived(sizeOf(id));
  const phone = $derived(viewport.phone);

  const topStep = $derived(meta.heightStates[meta.heightStates.length - 1]);
  const phoneHeight = $derived(topStep ? topStep.min + 13 : 0);
  const height = $derived(phone ? phoneHeight : box.height);

  let widthState = $state('');
  let heightState = $state('');

  $effect(() => {
    const width = box.width;
    widthState = pickState(meta.widthStates, width, widthState);
  });

  $effect(() => {
    heightState = pickState(meta.heightStates, height, heightState);
  });

  const Cell = $derived(
    entry && store.page === 'terminal' && kindOf(id) === 'terminal' ? TerminalGroupCell : entry?.component,
  );

  const count = $derived(entry?.count ? entry.count() : null);
  const suffix = $derived(entry?.suffix ? entry.suffix() : null);

  const collapsed = $derived(phone && store.isCollapsed(id));

  function toggle(): void {
    store.toggleCollapsed(id);
  }

  let expanded = $state(false);

  const total = $derived(entry?.phoneTotal ? entry.phoneTotal() : null);
  const summary = $derived(collapsed && entry?.phoneSummary ? entry.phoneSummary() : null);

  const limit = $derived(phone && meta.phoneCap && !expanded ? meta.phoneCap : null);

  const scope = $derived(activeScopeFor(manifestById(`core.${id}`)));
</script>

<CellFrame
  {meta}
  {store}
  {count}
  {suffix}
  onRightControl={entry?.onRightControl}
  {instance}
  {widthState}
  {heightState}
  {collapsed}
  {summary}
  {total}
  {expanded}
  onToggleExpanded={() => (expanded = !expanded)}
  onToggleCollapse={toggle}
>
  {#snippet body()}
    {#if Cell}
      <Cell
        width={box.width}
        {height}
        {meta}
        {instance}
        {store}
        {collapsed}
        {phone}
        {limit}
        page={store.page}
        scope={scope}
        onToggleCollapse={toggle}
      />
    {:else}
      <p class="oc-cell-unavailable">{t(isPluginSlot(id) ? 'opscenter.cell.plugin_pending.body' : 'opscenter.cell.unavailable')}</p>
    {/if}
  {/snippet}
</CellFrame>

<style>
  @layer components {
    .oc-cell-unavailable {
      margin: 0;
      padding: 10px var(--oc-space-3);
      color: var(--oc-text-dim);
      font-size: var(--oc-fs-label);
    }
  }
</style>
