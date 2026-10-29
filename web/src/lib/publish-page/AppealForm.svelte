
<script lang="ts">
    import Button from '../base/Button.svelte';
    import Field from '../base/Field.svelte';
    import type { Translate } from '../sessions/types';
    import type { PageActions } from './actions';
    import type { PageStore } from './page-store.svelte';
    import type { SubRow } from './types';

    interface Props {
        store: PageStore;
        actions: PageActions;
        t: Translate;
        sub: SubRow;
        left: number;
        location: string;
        onNew: () => void;
    }
    const { store, actions, t, sub, left, location, onNew }: Props = $props();

    const MAX_APPEAL = 1000;

    let open = $state(false);
    let text = $state(t('publish.page.next.appeal.default'));
    let busy = $state(false);

    async function send(): Promise<void> {
        const body = text.trim() || t('publish.page.next.appeal.default');
        if (busy) return;
        busy = true;
        const result = await actions.appeal(sub.id, body, location);
        busy = false;
        if (result.ok) open = false;
    }
</script>

<div class="pp-appeal" data-pp="AppealForm">
    <p class="d-slot__why">{t('publish.page.next.appeal.lead', { reason: sub.reason, count: left })}</p>
    {#if open}
        <label class="d-field">{t('publish.page.next.appeal.label')}<Field multiline rows={3} maxlength={MAX_APPEAL} placeholder={t('publish.page.next.appeal.placeholder')} aria-label={t('publish.page.next.appeal.label')} bind:value={text} /></label>
        <div class="pp-foot">
            <Button variant="confirm" disabled={busy} onclick={() => void send()}>{t('publish.page.next.button.appeal_send')}</Button>
            <Button onclick={() => { open = false; store.setActionFailure('appeal', null); }}>{t('publish.page.next.button.appeal_cancel')}</Button>
        </div>
    {:else}
        <div class="pp-foot">
            <Button variant="confirm" id="d-appeal" onclick={() => (open = true)}>{t('publish.page.next.button.appeal', { count: left })}</Button>
            <Button onclick={onNew}>{t('publish.page.next.button.check_new')}</Button>
        </div>
    {/if}
    {#if store.failure.appeal}<p class="d-reason" data-tone="yellow" role="alert">{store.failure.appeal}</p>{/if}
</div>
