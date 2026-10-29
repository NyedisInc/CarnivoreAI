
<script lang="ts">
    import Button from '../base/Button.svelte';
    import IconButton from '../base/IconButton.svelte';
    import type { Translate } from '../sessions/types';
    import type { PageStore } from './page-store.svelte';

    interface Props {
        store: PageStore;
        t: Translate;
        onRefresh: () => void;
        onBack: () => void;
    }
    const { store, t, onRefresh, onBack }: Props = $props();

    const account = $derived(store.account);
    const notice = $derived(
        [store.failure.mine, store.failure.limits].find((line) => line !== null && (line === t('publish.page.failure.offline') || line === t('publish.page.failure.session_expired'))) ?? null,
    );
    const backShown = $derived(store.view === 'dossier' || store.rulesOpen);
</script>

<header class="pp-strip" data-pp="PaneStrip">
    <span class="pp-strip__back" hidden={!backShown}>
        <IconButton label={t('publish.page.strip.back_aria')} icon="arrow-left" iconSize={14} onclick={onBack} />
    </span>
    <h2 class="pp-strip__title">{t('publish.new.page_title')}</h2>
    <div class="d-strip" role="status">
        <span class="d-strip__h" data-own={!store.signedIn || !account?.handle ? '' : undefined}>
            {#if !store.signedIn}
                {t('publish.page.strip.signed_out')}
            {:else if account && account.handle}
                <b>{account.handle}</b><span class="d-strip__note">{" "}{account.handle_status === 'pending' ? t('publish.page.strip.handle_pending') : t('publish.page.strip.handle_confirmed')}</span>
            {:else if account}
                {t('publish.page.strip.no_handle')}
            {/if}
        </span>
        {#if notice}<span class="pp-strip__fail">{notice}</span>{/if}
    </div>
    <div class="pp-strip__controls">
        <Button size="sm" onclick={() => store.openRules()}>{t('publish.page.strip.rules')}</Button>
        <Button size="sm" onclick={onRefresh}>{t('publish.page.strip.refresh')}</Button>
    </div>
</header>
