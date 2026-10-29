<script lang="ts" generics="Row extends Record<string, unknown> & { id: string }">
  import type { Snippet } from 'svelte';
  import type { ColumnSpec } from '../engine/types';
  import DataTable from './DataTable.svelte';

  let {
    columns,
    rows,
    limit = null,
    phone = false,
    cell,
  }: {
    columns: ColumnSpec[];
    rows: Row[];
    limit?: number | null;
    phone?: boolean;
    cell: Snippet<[Row, ColumnSpec, number]>;
  } = $props();
</script>

<DataTable
  {columns}
  rows={limit === null ? rows : rows.slice(0, limit)}
  rowHeight={26}
  headHeight={26}
  showHead={!phone}
  compact={phone}
  rowKey={(row) => row.id}
  {cell}
/>
