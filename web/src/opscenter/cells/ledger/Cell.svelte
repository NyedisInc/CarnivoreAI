<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';
  import { FOLDS, readFold, writeFold, type LedgerFold } from '../../../lib/ledger-drawer/ledger-fold';

  const isFold = (value: unknown): value is LedgerFold => FOLDS.includes(value as LedgerFold);

  export const LEDGER_WIDGET = defineWidget({
    id: 'core.ledger',
    scope: 'global',
    actions: [],
    state: { fold: { home: 'shared', default: 'compact' as LedgerFold, valid: isFold, via: { read: readFold, write: (value: unknown) => { if (isFold(value)) writeFold(value); } } } },
  });
</script>

<script lang="ts">
  import type { CellProps } from '../../lib/cell';
  import DrawerLedger from '../../../lib/ledger-drawer/DrawerLedger.svelte';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import { useWidget } from '../../widgets/shell/define-widget.svelte';

  let props: CellProps & { drawer?: boolean } = $props();

  const widget = useWidget(LEDGER_WIDGET, () => props);
</script>

<WidgetShell {widget}>
  <DrawerLedger embedded={!props.drawer} {widget} />
</WidgetShell>
