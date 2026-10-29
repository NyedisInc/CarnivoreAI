
<script lang="ts">
  import Button from '../../base/Button.svelte';
  import { t } from '../../i18n/index.svelte';
  import { rowsSummary } from '../logic/report-rules';
  import { mark } from './ReportTree.svelte';
  import ReportTable from './ReportTable.svelte';
  import { wordMark } from '../logic/marks';

  let { rows }: { rows: Record<string, unknown>[] } = $props();
  let open = $state(false);
  const sum = $derived(rowsSummary(rows));
  const label = $derived(t(rows.length === 1 ? (open ? 'automations.page.rows.hide_one' : 'automations.page.rows.show_one') : open ? 'automations.page.rows.hide' : 'automations.page.rows.show', { n: rows.length }));
</script>

<div class="r-rows">
  <div class="r-rows-line">
    {#if sum.statusKey}
      <span class="r-rows-tally ap-num">{sum.tally.map((x) => `${x.count} ${x.word}`).join(', ')}</span>
    {:else}
      <span class="r-rows-cols">{sum.columns}</span>
    {/if}
    <Button size="sm" data-r-toggle aria-expanded={open} data-n={rows.length} onclick={() => (open = !open)}>{label}</Button>
  </div>
  {#if sum.notOk.length}
    <ul class="r-rows-bad">
      {#each sum.notOk as r, i (i)}
        <li>
          {#if r.name}<span class="r-rn">{r.name}</span>{/if}
          <span class="r-w">{@render mark(wordMark(r.word)!, 10, r.word)} <span>{r.word}</span></span>
          {#if r.text}<span class="r-rd">{r.text}</span>{/if}
        </li>
      {/each}
      {#if sum.notOkMore}<li class="r-note">{t('automations.page.rows.more_not_ok', { n: sum.notOkMore })}</li>{/if}
    </ul>
  {/if}
  {#if open}
    <div class="r-rows-body"><ReportTable {rows} /></div>
  {/if}
</div>
