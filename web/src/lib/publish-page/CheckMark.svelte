
<script lang="ts">
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import { resultKey, type CheckResult } from './report-format';
    import './marks.css';

    interface Props {
        result: CheckResult;
        shapeOnly?: boolean;
        size?: number;
        t?: Translate;
    }
    const { result, shapeOnly = false, size = 12, t = reactiveT }: Props = $props();

    const HUE: Record<CheckResult, string> = { passed: 'green', did_not_pass: 'yellow', note: 'muted', skipped: 'muted', not_run: 'muted', running: 'green' };
    const word = $derived(t(resultKey(result)));
</script>

<span class="pp-verdict" class:d-mk={shapeOnly} data-result={result} data-hue={HUE[result]} role={shapeOnly ? 'img' : undefined} aria-label={shapeOnly ? word : undefined}>
    <svg class="pp-verdict__ic" width={size} height={size} viewBox="0 0 12 12" aria-hidden="true">
        {#if result === 'passed'}
            <rect x="1.5" y="1.5" width="9" height="9" fill="currentColor" stroke="currentColor" />
            <path d="m3.5 6.2 1.8 1.8 3.2-3.8" fill="none" stroke="var(--oc-ground-page)" stroke-width="1.3" />
        {:else if result === 'did_not_pass'}
            <path d="M1.5 1.5h5l1.5 2h2.5v7h-9Z" fill="none" stroke="currentColor" />
        {:else if result === 'note' || result === 'skipped'}
            <rect x="1.5" y="1.5" width="9" height="9" fill="none" stroke="currentColor" />
            <path d="M3.5 6h5" fill="none" stroke="currentColor" stroke-width="1.3" />
        {:else if result === 'running'}
            <rect x="1.5" y="1.5" width="9" height="9" fill="none" stroke="currentColor" />
            <rect x="2" y="2" width="4" height="8" fill="currentColor" stroke="none" />
        {:else}
            <rect x="1.5" y="1.5" width="9" height="9" fill="none" stroke="currentColor" />
        {/if}
    </svg>
    {#if !shapeOnly}<span class="pp-stage__w">{word}</span>{/if}
</span>
