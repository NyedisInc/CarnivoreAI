
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import StageMark from './StageMark.svelte';
    import { STAGES, stageKey } from './stages';

    interface Props {
        t: Translate;
    }
    const { t }: Props = $props();
</script>

<div class="d-key" role="group" aria-label={t('publish.page.key.aria')}>
    <h3 class="pl-label d-key__lab">{t('publish.page.key.label')}</h3>
    <ul class="d-key__g">
        {#each STAGES as stage (stage)}
            <li class="d-key__i"><StageMark {stage} shapeOnly {t} /><span class="d-key__w">{t(stageKey(stage))}</span></li>
        {/each}
    </ul>
</div>
