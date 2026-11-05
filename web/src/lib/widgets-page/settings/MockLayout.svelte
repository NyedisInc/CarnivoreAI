
<script lang="ts">
    import type { Snippet } from 'svelte';
    import type { Translate } from '../../sessions/types';
    import { STAGE_H, STAGE_W, counterScale, mockScale } from './mock-model';
    import './mock.css';

    interface Props {
        sidePx: number;
        bottomPx: number;
        label: string;
        t: Translate;
        children?: Snippet;
    }
    const { sidePx, bottomPx, label, t, children }: Props = $props();

    let fitWidth = $state(0);
    const k = $derived(mockScale(fitWidth));
    const AGENTS = ['widgets.settings.try.agent_one', 'widgets.settings.try.agent_two'] as const;
    const LINES = [0, 1, 2] as const;
</script>

<div class="wp-mock" role="group" aria-label={label}>
    <div class="wp-mock__fit" bind:clientWidth={fitWidth}>
        <div class="wp-mock__scaler" style:height="{STAGE_H * k}px">
            <div class="wp-mock__stage" style:width="{STAGE_W}px" style:height="{STAGE_H}px" style:transform="scale({k})" style:--wp-mock-k={counterScale(k)} style:--mock-side="{sidePx}px" style:--mock-bottom="{bottomPx}px">
                <div class="wp-mock__cells" aria-hidden="true">
                    {#each AGENTS as agent (agent)}
                        <div class="wp-mock__cell">
                            <div class="wp-mock__head">{t(agent)}</div>
                            <div class="wp-mock__body">
                                <div class="wp-mock__lines">{#each LINES as line (line)}<span class="wp-mock__line">{t('widgets.settings.mock.line')}</span>{/each}</div>
                            </div>
                        </div>
                    {/each}
                </div>
                {@render children?.()}
            </div>
        </div>
    </div>
</div>
