
<script lang="ts">
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import { stageKey, type StageKey } from './stages';
    import './marks.css';

    interface Props {
        stage: StageKey;
        shapeOnly?: boolean;
        size?: number;
        t?: Translate;
    }
    const { stage, shapeOnly = false, size = 12, t = reactiveT }: Props = $props();

    const HUE: Record<StageKey, string> = { submitted: 'muted', in_review: 'cyan', approved: 'green', rejected: 'coral' };
    const word = $derived(t(stageKey(stage)));
</script>

<span class="pp-stage" class:d-mk={shapeOnly} data-stage={stage} data-hue={HUE[stage]} role={shapeOnly ? 'img' : undefined} aria-label={shapeOnly ? word : undefined}>
    <svg class="pp-stage__ic" width={size} height={size} viewBox="0 0 12 12" aria-hidden="true">
        {#if stage === 'submitted'}
            <rect x="1.5" y="1.5" width="9" height="9" fill="none" stroke="currentColor" />
        {:else if stage === 'in_review'}
            <rect x="1.5" y="1.5" width="9" height="9" fill="none" stroke="currentColor" />
            <rect x="2" y="2" width="4" height="8" fill="currentColor" stroke="none" />
        {:else if stage === 'approved'}
            <rect x="1.5" y="1.5" width="9" height="9" fill="none" stroke="currentColor" />
            <path d="m3.5 6.2 1.8 1.8 3.2-3.8" fill="none" stroke="currentColor" stroke-width="1.3" />
        {:else}
            <rect x="1.5" y="1.5" width="9" height="9" fill="none" stroke="currentColor" />
            <path d="M3.5 3.5l5 5M8.5 3.5l-5 5" stroke="currentColor" />
        {/if}
    </svg>
    {#if !shapeOnly}<span class="pp-stage__w">{word}</span>{/if}
</span>
