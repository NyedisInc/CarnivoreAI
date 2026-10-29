<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';

  export const BROWSER_WIDGET = defineWidget({ id: 'core.browser', scope: 'global', actions: [], state: {} });
</script>

<script lang="ts">
  import type { CellProps } from '../../lib/cell';
  import { inputFocus } from '../../lib/input-focus.svelte';
  import { instanceName } from '../../engine/meta';
  import type { SlotId } from '../../engine/types';
  import BrowserView from '../../../lib/browser/BrowserView.svelte';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import { useWidget } from '../../widgets/shell/define-widget.svelte';

  let props: CellProps = $props();
  const instance = $derived(props.instance);

  const widget = useWidget(BROWSER_WIDGET, () => props);

  const browserId = $derived(instanceName(instance as SlotId));

  $effect(() => {
    const slot = instance;
    return () => inputFocus.forget(slot);
  });

  function dropFocus(event: FocusEvent): void {
    const next = event.relatedTarget;
    const host = event.currentTarget;
    if (next instanceof Node && host instanceof Node && host.contains(next)) return;
    inputFocus.release(instance);
  }
</script>

<WidgetShell {widget} bare>
<div class="oc-browser-cell" onfocusincapture={() => inputFocus.claim(instance)} onfocusoutcapture={dropFocus}>
  {#key browserId}
    <BrowserView {browserId} compact />
  {/key}
</div>
</WidgetShell>

<style>
  @layer components {
    .oc-browser-cell {
      width: 100%;
      height: 100%;
      min-height: 0;
    }
  }
</style>
