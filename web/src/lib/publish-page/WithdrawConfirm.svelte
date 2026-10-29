
<script lang="ts">
    import Button from '../base/Button.svelte';
    import type { Translate } from '../sessions/types';
    import type { PageActions } from './actions';
    import type { PageStore } from './page-store.svelte';
    import type { SubRow } from './types';

    interface Props {
        store: PageStore;
        actions: PageActions;
        t: Translate;
        sub: SubRow;
        location: string;
    }
    const { store, actions, t, sub, location }: Props = $props();

    let confirm = $state(false);
    let busy = $state(false);

    $effect(() => {
        if (store.withdrawAsk === sub.id) {
            confirm = true;
            store.withdrawAsk = null;
        }
    });

    async function withdraw(): Promise<void> {
        if (busy) return;
        busy = true;
        const result = await actions.withdraw(sub.id, location);
        busy = false;
        if (result.ok) confirm = false;
    }
</script>

<div class="pp-withdraw" data-pp="WithdrawConfirm">
    {#if confirm}
        <div class="pp-foot">
            <span class="d-reason" data-tone="secondary">{t('publish.page.next.withdraw.confirm', { version: sub.version })}</span>
            <Button variant="danger" disabled={busy} onclick={() => void withdraw()}>{t('publish.page.next.button.withdraw_yes')}</Button>
            <Button onclick={() => { confirm = false; store.setActionFailure('withdraw', null); }}>{t('publish.page.next.button.withdraw_no')}</Button>
        </div>
    {:else}
        <div class="pp-foot"><Button variant="danger" id="d-withdraw" onclick={() => (confirm = true)}>{t('publish.page.next.button.withdraw', { version: sub.version })}</Button></div>
    {/if}
    {#if store.failure.withdraw}<p class="d-reason" data-tone="yellow" role="alert">{store.failure.withdraw}</p>{/if}
</div>
