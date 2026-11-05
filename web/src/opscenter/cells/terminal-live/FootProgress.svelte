
<script lang="ts">
    import { progressFor, progressLabel } from '../../../lib/session-badges';

    const { sessionId }: { sessionId: string } = $props();

    const bar = $derived(progressFor(sessionId));
    const label = $derived(bar ? progressLabel(bar) : null);
    const striped = $derived(!!bar && (bar.state === 'indeterminate' || bar.percent === null));
</script>

{#if bar && label}
    <span class="oc-tf-progress" data-foot-progress data-state={bar.state} data-striped={striped ? '1' : undefined} role="progressbar"
        aria-label={label.title} aria-valuemin="0" aria-valuemax="100" aria-valuenow={striped ? undefined : bar.percent ?? undefined}
        title={label.title}><span class="oc-tf-progress__fill" style="width: {striped ? 100 : bar.percent ?? 0}%"></span></span>
{/if}

<style>
    @layer components {
        .oc-tf-progress {
            position: absolute;
            inset: 0 0 auto 0;
            height: 2px;
            z-index: 1;
            background: var(--oc-line-faint);
            color: var(--oc-cyan);
            pointer-events: auto;
        }

        .oc-tf-progress[data-state='error'] {
            color: var(--oc-coral);
        }

        .oc-tf-progress[data-state='paused'] {
            color: var(--oc-yellow);
        }

        .oc-tf-progress__fill {
            display: block;
            height: 100%;
            background: currentColor;
        }

        .oc-tf-progress[data-striped='1'] .oc-tf-progress__fill {
            background: repeating-linear-gradient(90deg, currentColor 0 6px, transparent 6px 12px);
        }
    }
</style>
