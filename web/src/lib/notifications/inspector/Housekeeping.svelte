
<script lang="ts">
    import Check from '../../../opscenter/ui/Check.svelte';
    import { Button, Fold } from '../../base';
    import type { Translate } from '../../sessions/types';
    import MutesPanel from '../mute/MutesPanel.svelte';
    import SyncPanel from '../sync/SyncPanel.svelte';
    import { linkKindKey, linkReasonKey } from '../matrix/logic';
    import { matrix, setPaused } from '../matrix/store.svelte';

    interface Props { advanced: boolean; onAdvanced: () => void; t: Translate }
    const { advanced, onAdvanced, t }: Props = $props();
    const link = $derived(matrix.settings.link);
</script>

<section class="ins-panel ins-house" data-ins="house">
    <div class="ins-bar"><h2>{t('notify.routing.house.title')}</h2></div>
    <div class="ins-house__pause">
        <Check role="switch" label={t('settings.notify.pause.label')} hint={t('settings.notify.pause.hint')} checked={matrix.settings.paused} data-ins="pause" onToggle={(next) => void setPaused(next)} />
    </div>
    {#if !advanced && link.kind === 'none'}
        <div class="ins-warn ins-warn--row" role="note" data-ins="no-link">
            <span>{t('notify.routing.house.no_link')}</span>
            <Button size="sm" data-ins="no-link-go" onclick={onAdvanced}>{t('notify.routing.house.no_link.go')}</Button>
        </div>
    {/if}
    <Fold label={t('notify.routing.house.muted')}>{#snippet children()}<MutesPanel {t} />{/snippet}</Fold>
    <Fold label={t('notify.routing.house.sync')}>{#snippet children()}<SyncPanel {t} />{/snippet}</Fold>
    {#if advanced}
        <Fold label={t('notify.routing.house.link')} open>
            {#snippet children()}
                <div class="ins-link" data-ins="link-panel">
                    <p class="ins-dim">{t('notify.routing.house.link.what')}</p>
                    <p><span class="ins-chip" data-ins="link-kind">{t(linkKindKey(link.kind))}</span>{#if link.base} <code data-ins="link-base">{link.base}</code>{/if}</p>
                    <p class="ins-dim" data-ins="link-reason">{t(linkReasonKey(link.reason))}</p>
                </div>
            {/snippet}
        </Fold>
    {/if}
</section>
