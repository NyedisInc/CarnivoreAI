<script lang="ts" module>
  import { defineWidget } from '../define-widget.svelte';

  export const PROBE_WIDGET = defineWidget({
    id: 'probe.shell',
    scope: 'global',
    actions: [
      { id: 'mode:edit', labelKey: 'opscenter.cell.notes.edit', kind: 'choice' },
      { id: 'save', labelKey: 'opscenter.cell.notes.save_now', group: 'save' },
    ],
    state: { tick: { home: 'placement', default: 0, valid: (value: unknown): value is number => typeof value === 'number' } },
  });
</script>

<script lang="ts">
  import WidgetShell from '../WidgetShell.svelte';
  import { useWidget } from '../define-widget.svelte';
  import type { WidgetStatus } from '../widget-status';
  import { META } from '../../../engine/meta';

  let { status = 'ready', note = '', withControls = true, runs = [] }: {
    status?: WidgetStatus;
    note?: string;
    withControls?: boolean;
    runs?: string[];
  } = $props();

  const widget = useWidget(PROBE_WIDGET, () => ({ width: 300, height: 200, meta: META.notes, instance: 'probe-1' }), () => ({
    'mode:edit': { on: true, run: () => runs.push('mode:edit') },
    save: { run: () => runs.push('save') },
  }));
</script>

{#snippet controls(place: 'header' | 'body' | 'corner')}<button data-base-exempt="test fixture probe, not shipped UI" type="button" data-probe-controls={place}>c</button>{/snippet}

<WidgetShell {widget} {status} {note} controls={withControls ? controls : undefined}>
  <p data-probe-body>body</p>
</WidgetShell>
