<script lang="ts" module>
  import { defineWidget } from '../../opscenter/widgets/shell/define-widget.svelte';
  import { PLUGIN_VIEW_ID } from '../../opscenter/cells/plugin-view/constants';

  export const DECLARATIVE_WIDGET_DEF = defineWidget({ id: PLUGIN_VIEW_ID, scope: 'global', actions: [], state: {} });
</script>

<script lang="ts">
  import type { CellProps } from '../../opscenter/lib/cell';
  import { t } from '../i18n/index.svelte';
  import WidgetShell from '../../opscenter/widgets/shell/WidgetShell.svelte';
  import { useWidget } from '../../opscenter/widgets/shell/define-widget.svelte';
  import CplugSurface from './CplugSurface.svelte';
  import type { Surface } from './api';
  import { panelOf } from './panel-views.svelte';

  let props: CellProps = $props();

  const widget = useWidget(DECLARATIVE_WIDGET_DEF, () => props);

  const entry = $derived.by(() => {
    const [kind = '', tail = ''] = (props.instance ?? '').split(':');
    const live = panelOf(kind);
    return live && live.tail === tail ? live : undefined;
  });
</script>

<WidgetShell {widget} status={entry ? 'ready' : 'none'} note={t('cplug_ui.panel_off')}>
  {#if entry && widget.visible !== 'parked'}
    {#key entry.key}
      <CplugSurface plugin={entry.plugin} surface={'widget' as Surface} bar={false} {t} />
    {/key}
  {/if}
</WidgetShell>
