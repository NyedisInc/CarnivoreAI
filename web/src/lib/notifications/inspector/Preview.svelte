
<script lang="ts">
    import NotifyCard from '../../notify-card/NotifyCard.svelte';
    import type { Translate } from '../../sessions/types';
    import type { Sample } from './logic';

    interface Props { kind: 'app' | 'desk' | 'phone'; sample: Sample | null; off?: boolean; corner?: boolean; level?: string; t: Translate }
    const { kind, sample, off = false, corner = false, level = '', t }: Props = $props();
    const ICON = '/static/assets/icons/icon-180.png';
</script>

{#snippet card()}
    {#if sample}<div class="ins-sample"><NotifyCard card={sample.card} kind={sample.kind} body={sample.body} typing={false} /></div>{/if}
{/snippet}

<div class="ins-pf ins-pf--{kind}" data-off={off ? '' : undefined} data-frame={kind}>
    {#if kind === 'app'}
        <div class="ins-pf__bar"><i></i><i></i><i></i><span>{t('notify.routing.frame.app')}</span></div>
        <div class="ins-pf__body">
            <div class="ins-pf__ghost"><span>{t('notify.routing.frame.sessions')}</span><span></span><span></span><span></span></div>
            <div class="ins-pf__sample">{@render card()}</div>
        </div>
    {:else if kind === 'desk'}
        <div class="ins-pf__menu"><b>{t('notify.routing.frame.app')}</b><span>{t('notify.routing.frame.menu.file')}</span><span>{t('notify.routing.frame.menu.edit')}</span><span>{t('notify.routing.frame.menu.window')}</span><span class="ins-grow-fill"></span><span>{t('notify.routing.frame.clock')}</span></div>
        <div class="ins-pf__stack">
            {#if sample}
                <div class="ins-mac" data-ins="mac-banner">
                    <img class="ins-mac__ic" src={ICON} alt="" width="36" height="36" />
                    <div class="ins-mac__tx"><div class="ins-mac__t">{sample.title}</div><div class="ins-mac__s">{sample.sub}</div><div class="ins-mac__b">{sample.body}</div></div>
                    <div class="ins-mac__ts">{t('notify.routing.frame.now')}</div>
                </div>
            {/if}
            {#if corner}<div class="ins-pf__corner" data-ins="corner-card">{@render card()}</div>{:else}<div class="ins-pf__nocorner">{t('notify.routing.frame.no_corner')}</div>{/if}
        </div>
    {:else}
        <div class="ins-pf__status"><span>{t('notify.routing.frame.time')}</span></div>
        <div class="ins-pf__date">{t('notify.routing.frame.date')}</div>
        <div class="ins-pf__time">{t('notify.routing.frame.time')}</div>
        {#if sample}
            <div class="ins-ios" data-ins="phone-banner">
                <img class="ins-ios__ic" src={ICON} alt="" width="38" height="38" />
                <div class="ins-ios__tx"><div class="ins-ios__t">{sample.title}</div><div class="ins-ios__s">{sample.sub}</div><div class="ins-ios__b">{sample.body}</div>{#if level}<div class="ins-ios__lv">{level}</div>{/if}</div>
                <div class="ins-ios__ts">{t('notify.routing.frame.now')}</div>
            </div>
        {/if}
    {/if}
</div>
