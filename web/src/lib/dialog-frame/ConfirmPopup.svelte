
<script lang="ts">
    import type { HTMLAttributes } from 'svelte/elements';
    import AnchoredPopup from './AnchoredPopup.svelte';
    import Button from '../base/Button.svelte';

    interface Props extends Omit<HTMLAttributes<HTMLDivElement>, 'role' | 'class' | 'style' | 'children'> {
        label: string;
        message: string;
        anchor?: HTMLElement | null;
        cancelLabel: string;
        confirmLabel: string;
        busy?: boolean;
        onConfirm: () => void;
        onCancel: () => void;
        confirmProps?: Record<string, string>;
        cancelProps?: Record<string, string>;
    }

    let { label, message, anchor = null, cancelLabel, confirmLabel, busy = false, onConfirm, onCancel, confirmProps = {}, cancelProps = {}, ...rest }: Props = $props();
</script>

<AnchoredPopup {...rest} class="oc-confirm-popup" role="alertdialog" {label} {anchor} dismissable={!busy} initialFocus="[data-confirm-cancel]" onClose={onCancel}>
    <p class="oc-confirm-popup__line">{message}</p>
    <div class="oc-confirm-popup__foot">
        <Button size="sm" data-confirm-cancel {...cancelProps} onclick={onCancel}>{cancelLabel}</Button>
        <Button variant="danger" size="sm" disabled={busy} data-confirm-go {...confirmProps} onclick={onConfirm}>{confirmLabel}</Button>
    </div>
</AnchoredPopup>

<style>
    @layer components {
        :global(.oc-confirm-popup) {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-3);
            box-sizing: border-box;
            width: calc(20 * var(--oc-space-4));
            max-width: calc(100vw - 2 * var(--oc-space-4));
            padding: var(--oc-space-3);
        }

        .oc-confirm-popup__line {
            margin: 0;
            color: var(--oc-text-bright);
            font-size: var(--oc-fs-body);
        }

        .oc-confirm-popup__foot {
            display: flex;
            justify-content: flex-end;
            gap: var(--oc-space-2);
        }
    }
</style>
