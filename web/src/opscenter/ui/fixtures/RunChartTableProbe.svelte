<script lang="ts">
  import RunChartTable from '../RunChartTable.svelte';

  let { rows, limit, phone }: { rows: { id: string }[]; limit: number | null; phone: boolean } = $props();
  const columns = [{ key: 'id', headKey: 'opscenter.value.unknown', minPx: 40, weight: 1 }];
</script>

{#snippet probeCell(row: { id: string })}
  <span data-probe-cell={row.id}>{row.id}</span>
{/snippet}

<RunChartTable {columns} {rows} {limit} {phone} cell={probeCell} />
