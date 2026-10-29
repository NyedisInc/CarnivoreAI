
<script lang="ts">
    import { resourcePush, scaleStep, t as reactiveT, type Translate } from '../sdk';
    import { LimitGauge } from '../sdk/ui';
    import {
        JOBS_FAMILY,
        bytesText,
        cancelJob,
        codeSentence,
        errorSentence,
        fetchJob,
        jobFinished,
        type Fetcher,
        type JobView,
    } from './crate-api';

    interface Props {
        jobId: string;
        t?: Translate;
        fetcher?: Fetcher;
        onFinish?: (job: JobView) => void;
    }
    const { jobId, t = reactiveT, fetcher, onFinish }: Props = $props();

    const POLL_MS = 5000;

    let job = $state<JobView | null>(null);
    let problem = $state('');
    let cancelling = $state(false);
    let told = false;
    let generation = 0;

    const running = $derived(!!job && !jobFinished(job));
    const percent = $derived(job?.percent ?? null);
    const label = $derived(job ? t(`cplug.crate.job.kind.${job.kind ?? 'export'}`) : t('cplug.crate.job.reading'));
    const phaseWord = $derived(job?.phase ? t(`cplug.crate.job.phase.${job.phase}`) : '');
    const counts = $derived(
        job && job.totalBytes
            ? t('cplug.crate.job.bytes', { done: bytesText(job.doneBytes), total: bytesText(job.totalBytes) })
            : '',
    );
    const files = $derived(job && job.filesTotal ? t('cplug.crate.job.files', { done: job.filesDone ?? 0, count: job.filesTotal }) : '');

    async function load(id: string): Promise<void> {
        const mine = ++generation;
        try {
            const view = await fetchJob(id, fetcher);
            if (mine !== generation) return;
            job = view;
            problem = '';
            if (jobFinished(view) && !told) {
                told = true;
                onFinish?.(view);
            }
        } catch (error) {
            if (mine !== generation) return;
            problem = errorSentence(error, t);
        }
    }

    async function cancel(): Promise<void> {
        cancelling = true;
        try {
            await cancelJob(jobId, fetcher);
        } catch (error) {
            problem = errorSentence(error, t);
        } finally {
            cancelling = false;
        }
    }

    $effect(() => {
        const id = jobId;
        job = null;
        told = false;
        void load(id);
        return resourcePush().pushOrPoll(() => {
            if (!jobFinished(job)) void load(id);
        }, POLL_MS, [`${JOBS_FAMILY}:${id}`]);
    });
</script>

<div class="crt-job" data-crt-job={jobId} data-crt-state={job?.state ?? 'reading'}>
    <div class="crt-job__head">
        <span class="pl-label">{label}</span>
        {#if phaseWord && running}<span class="tm__sub" data-crt-phase>{phaseWord}</span>{/if}
        {#if running}
            <button type="button" class="oc-btn oc-btn--sm" data-crt-cancel disabled={cancelling} onclick={() => void cancel()}>
                {t('cplug.crate.job.cancel')}
            </button>
        {/if}
    </div>
    {#if running}
        <LimitGauge variant="fill" pct={percent} scale={percent === null ? null : scaleStep(percent)}
            meterText={counts || phaseWord || label} height={6} />
        {#if counts || files}<p class="tm__sub" data-crt-counts>{[counts, files].filter(Boolean).join(', ')}</p>{/if}
    {:else if job?.state === 'done'}
        <p class="tm__note" role="status" data-crt-done>{t(`cplug.crate.job.done.${job.kind ?? 'export'}`)}</p>
    {:else if job?.state === 'cancelled'}
        <p class="tm__problem" role="status" data-crt-cancelled>{t('cplug.crate.job.cancelled')}</p>
    {:else if job?.state === 'failed'}
        <p class="tm__problem" role="alert" data-crt-failed>
            {job.error ? codeSentence(job.error.code, job.error.detail, t) : t('cplug.crate.job.failed')}
        </p>
    {/if}
    {#if problem}<p class="tm__problem" role="alert" data-crt-problem>{problem}</p>{/if}
</div>

<style>
    @layer components {
        .crt-job {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-2);
        }

        .crt-job__head {
            display: flex;
            align-items: center;
            gap: var(--oc-space-3);
        }

        .crt-job__head :global(.oc-btn) {
            margin-left: auto;
        }
    }
</style>
