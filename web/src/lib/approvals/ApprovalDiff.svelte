<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import { diffValue, type DiffRow } from './approvals-model';

  let { rows }: { rows: DiffRow[] } = $props();
</script>

<table class="ap-diff" data-approval-diff aria-label={t('approvals.diff.label')}>
  <thead>
    <tr><th scope="col">{t('approvals.diff.field')}</th><th scope="col">{t('approvals.diff.before')}</th>
      <th scope="col">{t('approvals.diff.after')}</th></tr>
  </thead>
  <tbody>
    {#each rows as row (row.field)}
      <tr data-diff-field={row.field}>
        <th scope="row" class="ap-diff__field">{row.field}</th>
        <td class="ap-diff__before">{row.before === null || row.before === undefined ? t('approvals.diff.none') : diffValue(row.before)}</td>
        <td class="ap-diff__after">{row.after === null || row.after === undefined ? t('approvals.diff.removed') : diffValue(row.after)}</td>
      </tr>
    {/each}
  </tbody>
</table>

<style>
  @layer components {
    .ap-diff {
      width: 100%;
      border-collapse: collapse;
      font-family: var(--font-mono);
      font-size: var(--oc-fs-micro);
      table-layout: fixed;
    }
    .ap-diff th,
    .ap-diff td {
      padding: var(--oc-space-1);
      text-align: left;
      vertical-align: top;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      box-shadow: inset 0 calc(-1 * var(--oc-border, 1px)) 0 var(--pl-line-quiet);
    }
    .ap-diff thead th,
    .ap-diff__field {
      color: var(--oc-text-muted);
      font-weight: normal;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    .ap-diff__before { color: var(--oc-text-muted); }
    .ap-diff__after { color: var(--oc-orange); }
  }
</style>
