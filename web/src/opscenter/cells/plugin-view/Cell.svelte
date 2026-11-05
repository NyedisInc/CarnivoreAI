<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';
  import { PLUGIN_VIEW_ID } from './constants';

  export const PLUGIN_VIEW_WIDGET = defineWidget({ id: PLUGIN_VIEW_ID, scope: 'global', actions: [], state: {} });
</script>

<script lang="ts">
  import type { CellProps } from '../../lib/cell';
  import { t } from '../../../lib/i18n/index.svelte';
  import Tag from '../../../lib/base/Tag.svelte';
  import ViewFrame from '../../../lib/cplug-ui/ViewFrame.svelte';
  import { declaredViewActions, type ViewAction } from '../../../lib/cplug-ui/view-actions';
  import { declareWidgetActions } from '../../widgets/menu/declared-actions.svelte';
  import { VIEW_ACTION_SOURCE } from './constants';
  import { openWidgetMenu } from '../../../lib/item-menu/widget-gesture';
  import { panelOf } from '../../../lib/cplug-ui/panel-views.svelte';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import { useWidget } from '../../widgets/shell/define-widget.svelte';
  import { watchOnScreen } from '../files/on-screen';

  let props: CellProps = $props();

  const widget = useWidget(PLUGIN_VIEW_WIDGET, () => props);

  let root = $state<HTMLElement | undefined>();
  let onScreen = $state(false);
  $effect(() => (root ? watchOnScreen(root, (yes) => (onScreen = yes)) : undefined));
  const parked = $derived(widget.visible === 'parked');
  const seen = $derived(widget.visible === 'shown' && onScreen);

  let view = $state<ViewFrame | undefined>();
  let viewActions = $state<ViewAction[]>([]);

  $effect(() => {
    const host = widget.frame?.hostId;
    if (!host || !viewActions.length || widget.visible !== 'shown') return;
    return declareWidgetActions(host, VIEW_ACTION_SOURCE, declaredViewActions(viewActions, (id, on) => view?.sendAction(id, on)));
  });

  $effect(() => {
    void entry?.key;
    if (parked) viewActions = [];
    return () => { viewActions = []; };
  });

  const entry = $derived.by(() => {
    const [kind = '', tail = ''] = (props.instance ?? '').split(':');
    const live = panelOf(kind);
    return live && live.tail === tail ? live : undefined;
  });
</script>

{#snippet mark()}
  {#if entry}
    <Tag tone={entry.plugin.unverified ? 'warn' : 'accent'} data-cplug-mark data-unverified={entry.plugin.unverified ? '' : undefined}>{t(entry.plugin.unverified ? 'cplug_ui.mark.unverified' : 'cplug_ui.mark.third_party')}</Tag>
  {/if}
{/snippet}

<div class="cu-panelcell" data-panel-cell bind:this={root}>
  <WidgetShell {widget} status={entry ? 'ready' : 'none'} note={t('cplug_ui.panel_off')} controls={entry ? mark : undefined}>
    {#if entry}
      {#if widget.frame?.suppressed}
        <div class="cu-panelcell__mark" data-widget-controls="body">{@render mark()}</div>
      {/if}
      {#if !parked}
      {#key entry.key}
        <ViewFrame plugin={entry.plugin} view={entry.view} surface="panel" bar={false} fill visible={seen} {t}
          bind:this={view} onActions={(list) => (viewActions = list)} onMenu={openWidgetMenu} />
      {/key}
      {/if}
    {/if}
  </WidgetShell>
</div>

<style>
  @layer components {
    .cu-panelcell {
      display: flex;
      flex-direction: column;
      height: 100%;
      min-height: 0;
      min-width: 0;
    }
    .cu-panelcell__mark {
      flex: 0 0 auto;
      padding: var(--oc-space-1) var(--oc-space-1) 0;
    }
  }
</style>
