
<script lang="ts">
    import Button from '../base/Button.svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import ModalShell from '../dialog-frame/ModalShell.svelte';
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

<ModalShell look="titlerow" {title} overlayClass="na-flow" onCancel={() => close(null)}>
    <p class="modal-description" data-fed-confirm-body>{body}</p>
    {#snippet footer()}
        <Button data-fed-confirm-cancel onclick={() => close(null)}>{t('hosts.fed.cancel')}</Button>
        <Button variant={calm ? 'confirm' : 'danger'} data-fed-confirm-go onclick={() => close(true)}>{confirmLabel}</Button>
    {/snippet}
</ModalShell>
