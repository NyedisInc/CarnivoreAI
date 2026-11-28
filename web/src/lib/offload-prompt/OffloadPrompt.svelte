<!-- offloaded to the backup vault -->
<script lang="ts">
    import { Button } from '../base';
    import ModalShell from '../dialog-frame/ModalShell.svelte';
    import { t } from '../i18n/index.svelte';
    import { dateText } from '../publish-page/format';
    import { restoreAllowed, type OffloadedDetails } from './offload-api';
    import { sizeText } from './size-text';

    interface Props {
        name: string;
        details: OffloadedDetails | null;
        restore: () => Promise<string>;
        followUp?: boolean;
        close: (value: true | null) => void;
    }

    const { name, details, restore, followUp = false, close }: Props = $props();

    let busy = $state(false);
    let failure = $state('');

    const canRestore = $derived(restoreAllowed(details));
    const count = $derived(details?.conversations.length ?? 0);
    const message = $derived(
        count > 1 ? t('offload.prompt.message.many', { name, count }) : t('offload.prompt.message.one', { name }),
    );
    const when = $derived(details && details.offloadedAt > 0 ? dateText(details.offloadedAt * 1000, t) : '');
    const facts = $derived(
        !details || details.unreadable
            ? ''
            : when
              ? t('offload.prompt.facts', { size: sizeText(details.bytes, t), date: when })
              : t('offload.prompt.facts_nodate', { size: sizeText(details.bytes, t) }),
    );
    const note = $derived(
        details?.unreadable ? t('offload.prompt.unreadable') : canRestore ? t(followUp ? 'offload.prompt.slow_then' : 'offload.prompt.slow') : t('offload.prompt.turn_on'),
    );

    async function go(): Promise<void> {
        if (busy) return;
        busy = true;
        failure = '';
        const why = await restore();
        busy = false;
        if (why === '') close(true);
        else failure = why;
    }
</script>

<ModalShell look="titlerow" closable={false} title={t('offload.prompt.title')} onCancel={() => close(null)}>
    <div class="modal-message" data-offload-message>{message}</div>
    {#if facts}<div class="modal-description" data-offload-facts>{facts}</div>{/if}
    <div class="modal-description" data-offload-note>{note}</div>
    {#if failure}<div class="modal-description" role="alert" data-offload-failure>{failure}</div>{/if}
    {#snippet footer()}
        <Button data-offload-cancel onclick={() => close(null)}>{canRestore ? t('offload.prompt.cancel') : t('offload.prompt.close')}</Button>
        {#if canRestore}
            <Button variant="confirm" data-offload-restore disabled={busy} onclick={go}>{busy ? t('offload.prompt.restoring') : t('offload.prompt.restore')}</Button>
        {/if}
    {/snippet}
</ModalShell>
