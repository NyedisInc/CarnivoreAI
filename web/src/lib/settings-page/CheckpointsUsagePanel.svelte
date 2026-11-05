
<script lang="ts">
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import List from '../base/List.svelte';
    import ListRow from '../base/ListRow.svelte';
    import State from '../base/State.svelte';
    import './panel-kit/panel-kit.css';
    import { checkpointUsage, releaseCheckpointUsage } from '../../opscenter/api/session-checkpoints.svelte';
    import { sizeText } from '../checkpoints/api';

    const { t = reactiveT }: { t?: Translate } = $props();

    const res = checkpointUsage();
    $effect(() => () => releaseCheckpointUsage());

    const repos = $derived(res.data?.repos ?? null);
    const total = $derived((repos ?? []).reduce((sum, r) => sum + r.bytes, 0));
</script>

<div class="tm" data-checkpoint-usage="panel">
    {#if repos && repos.length > 0}
        <p class="tm__sub" data-checkpoint-usage="total">{t('settings.checkpoints.total', { size: sizeText(total) })}</p>
        <List label={t('settings.checkpoints.list')} density="dense">
            {#each repos as repo (repo.work_tree)}
                <ListRow data-checkpoint-repo={repo.work_tree} primary={repo.work_tree}
                    secondary={repo.disabled_reason ? t(`settings.checkpoints.off.${repo.disabled_reason}`) : ''}
                    meta={t('settings.checkpoints.count', { n: repo.checkpoints, size: sizeText(repo.bytes) })} />
            {/each}
        </List>
    {:else if repos}
        <p class="tm__sub" data-checkpoint-usage="empty">{t('settings.checkpoints.empty')}</p>
    {:else if res.status === 'error' || res.status === 'unavailable'}
        <State kind="error" inline title={t('settings.checkpoints.unknown')} />
    {:else}
        <p class="tm__sub">{t('settings.checkpoints.loading')}</p>
    {/if}
</div>
