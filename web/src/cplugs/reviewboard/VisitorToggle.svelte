<script lang="ts">
  import { type VisitorRevision } from './board-visitor-revisions.svelte';
import { t } from '../sdk';

  let { rows, value, onchange }: { rows: VisitorRevision[]; value: number | null; onchange: (number: number | null) => void } = $props();
</script>

<label class="rb-uselect">{t('cplug.reviewboard.visitors.show')}
  <select data-field data-size="sm" data-visitor-toggle value={value === null ? '' : String(value)}
          onchange={(e) => onchange(e.currentTarget.value === '' ? null : Number(e.currentTarget.value))}>
    <option value="">{t('cplug.reviewboard.visitors.show_none')}</option>
    {#each rows as row (row.number)}<option value={String(row.number)}>{row.label}</option>{/each}
  </select>
</label>
