<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';
  import { PLUGIN_VIEW_ID } from './constants';

  export const PLUGIN_VIEW_WIDGET = defineWidget({ id: PLUGIN_VIEW_ID, scope: 'global', actions: [], state: {} });
</script>

<script lang="ts">
  import type { CellProps } from '../../lib/cell';
  import { t } from '../../../lib/i18n/index.svelte';
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

<div class="cu-panelcell" data-panel-cell bind:this={root}>
  <WidgetShell {widget} status={entry ? 'ready' : 'none'} note={t('cplug_ui.panel_off')}>
    {#if entry && !parked}
      {#key entry.key}
        <ViewFrame plugin={entry.plugin} view={entry.view} surface="panel" bar={false} fill visible={seen} {t}
          bind:this={view} onActions={(list) => (viewActions = list)} onMenu={openWidgetMenu} />
      {/key}
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
  }
</style>
