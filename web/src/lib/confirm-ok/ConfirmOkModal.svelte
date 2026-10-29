
<script lang="ts">
    import { Button } from '../base';
    import ModalShell from '../launchpad/ModalShell.svelte';

    interface Props {
        title: string;
        message: string;
        okLabel: string;
        cancelLabel: string;
        close: (value: boolean | null) => void;
    }

    const { title, message, okLabel, cancelLabel, close }: Props = $props();

    function focusOk(el: HTMLElement): void {
        queueMicrotask(() => el.focus());
    }
</script>

<ModalShell {title} overlayClass="text-prompt-modal" onCancel={() => close(null)}>
    {#snippet head()}
        <div class="text-prompt-modal__head">
            <span class="text-prompt-modal__verb">{title}</span>
        </div>
    {/snippet}
    <p class="modal-description" data-confirm-ok-message>{message}</p>
    {#snippet footer()}
        <Button data-confirm-ok-cancel onclick={() => close(null)}>{cancelLabel}</Button>
        <Button variant="confirm" data-confirm-ok-go onclick={() => close(true)} {@attach focusOk}>{okLabel}</Button>
    {/snippet}
</ModalShell>
