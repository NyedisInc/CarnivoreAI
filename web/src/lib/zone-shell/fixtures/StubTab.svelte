<script lang="ts">
  import { createRawSnippet } from 'svelte';
  import { useFrameHeader, useTabPane } from '../../../opscenter/shell/frame-header.svelte';
  import { declareWidgetActions } from '../../../opscenter/widgets/menu/declared-actions.svelte';
  import { defineWidget, useWidget, type WidgetPropsIn } from '../../../opscenter/widgets/shell/define-widget.svelte';

  let { name }: { name: string } = $props();

  const STUB = defineWidget({ id: 'test.stub', scope: 'global', actions: [], state: {} });
  const frame = useFrameHeader();
  const pane = useTabPane();
  const widget = useWidget(STUB, () => ({}) as WidgetPropsIn);

  $effect(() => {
    if (!frame) return;
    const stop = declareWidgetActions(frame.hostId, 'widget', [{ id: `act-${name}`, label: `act ${name}`, run: () => {} }]);
    frame.action = createRawSnippet(() => ({ render: () => `<span data-tool="${name}">tool ${name}</span>` }));
    return () => {
      stop();
      frame.action = null;
    };
  });
</script>

<span data-stub={name} data-host={frame?.hostId} data-pane-visible={pane?.visible} data-widget-visible={widget.visible}>{name}</span>
