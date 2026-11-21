
<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import Button from '../base/Button.svelte';
  import ListRow from '../base/ListRow.svelte';
  import Tag from '../base/Tag.svelte';
  import type { JobView } from './jobs-api';
  import JobDetails from './JobDetails.svelte';
  import { isLive, jobHead, jobWhere, stateTone, stateWord, whenWords } from './jobs-format';

  interface Props {
    job: JobView;
    canOpenWorker?: boolean;
    onStop?: (job: JobView) => void;
    onOpenWorker?: (job: JobView) => void;
  }
  const { job, canOpenWorker = false, onStop, onOpenWorker }: Props = $props();

  const mine = $derived(job.side === 'caller');
  const why = $derived(job.reason || job.error_detail || '');
  const when = $derived(whenWords(job));
  const long = $derived(job.body === 'agent');
</script>

<ListRow wrap primary={long ? jobWhere(job) : jobHead(job)} secondary={long ? undefined : jobWhere(job)} data-job={job.id} data-side={job.side} data-state={job.state}>
  {#snippet lead()}<Tag tone={stateTone(job.state)} data-jobs="state">{stateWord(job.state)}</Tag>{/snippet}
  {#snippet actions()}
    {#if mine && job.body === 'agent'}
      <Button variant="quiet" size="sm" disabled={!canOpenWorker} title={canOpenWorker ? undefined : t('pack.jobs.worker_missing')} data-jobs="open-worker"
        onclick={() => onOpenWorker?.(job)}>{t('pack.jobs.open_worker')}</Button>
    {/if}
    {#if mine && isLive(job)}
      <Button variant="quiet" size="sm" data-jobs="stop" onclick={() => onStop?.(job)}>{t('pack.jobs.stop.action')}</Button>
    {/if}
  {/snippet}
  {#snippet below()}
    {#if long}<div data-jobs="head">{jobHead(job)}</div>{/if}
    {#if when}<div data-jobs="when">{when}</div>{/if}
    {#if why}<div data-jobs="why">{why}</div>{/if}
    <JobDetails {job} />
  {/snippet}
</ListRow>
