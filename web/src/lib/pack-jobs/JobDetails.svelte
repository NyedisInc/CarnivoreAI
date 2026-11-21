
<script lang="ts">
  import '../pack-roster/roster.css';
  import { t } from '../i18n/index.svelte';
  import Fold from '../base/Fold.svelte';
  import type { JobView } from './jobs-api';

  const { job }: { job: JobView } = $props();

  const usage = $derived(job.usage ? Object.entries(job.usage).map(([k, v]) => `${k} ${typeof v === 'object' ? JSON.stringify(v) : String(v)}`).join(', ') : '');
  const facts = $derived<Array<[string, string]>>([
    ['exit', job.exit_code === null || job.exit_code === undefined ? '' : String(job.exit_code)],
    ['output', job.output_tail ?? ''],
    ['applied', (job.applied ?? []).join(', ')],
    ['deleted', (job.deleted ?? []).join(', ')],
    ['clashes', (job.clashes ?? []).join(', ')],
    ['ref', job.ref ?? ''],
    ['question', job.question ?? ''],
    ['result', job.result_text ?? ''],
    ['account', job.account_label ?? ''],
    ['usage', usage],
  ]);
  const present = $derived(facts.filter(([, value]) => value !== ''));
</script>

{#if present.length > 0}
  <div data-jobs="details"><Fold label={t('pack.jobs.details')}>
    <dl class="pp-facts" data-jobs="facts">
      {#each present as [key, value] (key)}
        <dt>{t(`pack.jobs.fact.${key}`)}</dt><dd class="pp-wrap" data-fact={key}>{value}</dd>
      {/each}
    </dl>
  </Fold></div>
{/if}
