
<script lang="ts">
    import { Button } from '../base';
    import ModalShell from '../dialog-frame/ModalShell.svelte';
    import { DANGER_START_FOCUS } from './focus-policy';

    interface Props {
        title: string;
        message: string;
        details: string;
        okLabel: string;
        cancelLabel: string;
        altLabel: string;
        variant: 'plain' | 'danger';
        close: (value: 'ok' | 'alt' | null) => void;
    }

    const { title, message, details, okLabel, cancelLabel, altLabel, variant, close }: Props = $props();

    const startOnCancel = $derived(variant === 'danger' && DANGER_START_FOCUS === 'cancel');

    function focusFirst(el: HTMLElement): void {
        queueMicrotask(() => el.focus());
    }

    function onEnter(event: KeyboardEvent): void {
        if (event.key !== 'Enter' || event.isComposing) return;
        const target = event.target instanceof Element ? event.target : null;
        if (target?.closest('[data-confirm-ok-cancel], [data-confirm-ok-alt]')) return;
        if (variant === 'danger' && !target?.closest('[data-confirm-ok-go]')) return;
        event.preventDefault();
        close('ok');
    }
</script>


<!-- svelte-ignore a11y_no_static_element_interactions -->
<div style:display="contents" onkeydown={onEnter}>
    <ModalShell {title} overlayClass="text-prompt-modal" onCancel={() => close(null)}>
        {#snippet head()}
            <div class="text-prompt-modal__head">
                <span class="text-prompt-modal__verb">{title}</span>
            </div>
        {/snippet}
        <div class="modal-message" data-confirm-ok-message>{message}</div>
        {#if details}<div class="modal-description" data-confirm-ok-details>{details}</div>{/if}
        {#snippet footer()}
            <Button data-confirm-ok-cancel onclick={() => close(null)} {@attach startOnCancel ? focusFirst : undefined}>{cancelLabel}</Button>
            {#if altLabel}<Button data-confirm-ok-alt onclick={() => close('alt')}>{altLabel}</Button>{/if}
            <Button variant={variant === 'danger' ? 'danger' : 'confirm'} data-confirm-ok-go onclick={() => close('ok')} {@attach startOnCancel ? undefined : focusFirst}>{okLabel}</Button>
        {/snippet}
    </ModalShell>
</div>
