
<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import { nonEmptyErrorMessageOr } from '../errors/failure-reason';
  import Button from '../base/Button.svelte';
  import ModalShell from '../dialog-frame/ModalShell.svelte';
  import { jobHead } from './jobs-format';
  import { jobsStore, type JobsStore } from './jobs-store.svelte';
  import type { JobView } from './jobs-api';

  interface Props {
    job: JobView;
    store?: JobsStore;
    close: (value: boolean) => void;
  }
  const { job, store = jobsStore, close }: Props = $props();

  let busy = $state(false);
  let problem = $state('');

  async function go(): Promise<void> {
    busy = true;
    problem = '';
    try {
      await store.stopJob(job.id);
      close(true);
    } catch (error) {
      problem = nonEmptyErrorMessageOr(error, t('pack.jobs.stop.failed'));
      busy = false;
    }
  }
</script>

<ModalShell look="titlerow" title={t('pack.jobs.stop.title')} dismissable={!busy} onCancel={() => close(false)}>
  <p class="modal-description" data-jobs="stop-what">{t('pack.jobs.stop.what', { job: jobHead(job), computer: job.computer ?? '' })}</p>
  {#if problem}<p class="tm__problem" role="alert" data-jobs="stop-error">{problem}</p>{/if}
  {#snippet footer()}
    <Button variant="secondary" disabled={busy} data-jobs="stop-cancel" onclick={() => close(false)}>{t('pack.jobs.stop.cancel')}</Button>
    <Button variant="danger" disabled={busy} data-jobs="stop-go" onclick={() => void go()}>{t(busy ? 'pack.jobs.stop.going' : 'pack.jobs.stop.go')}</Button>
  {/snippet}
</ModalShell>
