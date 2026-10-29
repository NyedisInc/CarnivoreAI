
<script lang="ts">
    import { t as reactiveT } from '../i18n/index.svelte';
    import ModalShell from '../launchpad/ModalShell.svelte';
    import type { Translate } from '../sessions/types';

    interface Props {
        title: string;
        body: string;
        confirmLabel: string;
        calm?: boolean;
        t?: Translate;
        close: (value: true | null) => void;
    }

    const { title, body, confirmLabel, calm = false, t = reactiveT, close }: Props = $props();
</script>

<ModalShell {title} overlayClass="text-prompt-modal na-flow" onCancel={() => close(null)}>
    {#snippet head()}
        <div class="text-prompt-modal__head">
            <span class="text-prompt-modal__verb">&raquo; {title}</span>
            <button type="button" class="modal-close" aria-label={t('modal.close')} onclick={() => close(null)}>&times;</button>
        </div>
    {/snippet}
    <p class="modal-description" data-fed-confirm-body>{body}</p>
    {#snippet footer()}
        <button class="modal-btn modal-btn-secondary" data-fed-confirm-cancel onclick={() => close(null)}>{t('hosts.fed.cancel')}</button>
        <button class="modal-btn {calm ? 'modal-btn-confirm' : 'modal-btn-danger'}" data-fed-confirm-go onclick={() => close(true)}>{confirmLabel}</button>
    {/snippet}
</ModalShell>
