
<script lang="ts">
    import { t as reactiveT, type Translate } from '../sdk';
    import { Button } from '../sdk/ui';
    import { movable, sortedCounts, type RolloutPreview } from './rollout-model';

    interface Props { preview: RolloutPreview | null; onreview: () => void; t?: Translate }
    const { preview, onreview, t = reactiveT }: Props = $props();
</script>

{#if preview && preview.total > 0}
    <p class="tm__sub" role="status" data-argent="tethered">{t('argent.rollout.tethered', { n: preview.tethered, m: preview.total })}</p>
    {#if preview.pending > 0}<p class="tm__sub" data-argent="tethered-pending">{t('argent.rollout.pending_first', { n: preview.pending })}</p>{/if}
    {#each sortedCounts(preview.reasons) as [reason, n] (reason)}
        <p class="tm__sub" data-argent-reason={reason}>{t('argent.rollout.count', { n, state: reason })}</p>
    {/each}
    {#if movable(preview) > 0}
        <div class="tm__actions">
            <Button size="sm" variant="confirm" data-argent="review" onclick={onreview}>{t('argent.rollout.review')}</Button>
        </div>
    {/if}
{/if}
