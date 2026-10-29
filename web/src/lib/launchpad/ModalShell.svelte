<!-- already exists already running -->
<script lang="ts">
    import { onMount, type Snippet } from 'svelte';
    import type { HTMLAttributes } from 'svelte/elements';
    import { t } from '../i18n/index.svelte';
    import IconButton from '../base/IconButton.svelte';

    /* tabindex= */
    const FOCUSABLE = [
        'a[href]',
        'button:not([disabled])',
        'input:not([disabled])',
        'select:not([disabled])',
        'textarea:not([disabled])',
        '[tabindex]:not([tabindex="-1"])',
    ].join(',');

    interface Props extends Omit<HTMLAttributes<HTMLDivElement>, 'title' | 'children' | 'role' | 'class'> {
        title: string;
        children: Snippet;
        footer?: Snippet;
        dismissable?: boolean;
        onCancel: () => void;
        overlayClass?: string;
        contentClass?: string;
        head?: Snippet;
        role?: 'dialog' | 'alertdialog';
        describedby?: string;
        trapFocus?: boolean;
        escapeGuard?: (event: KeyboardEvent) => boolean;
        width?: string;
        height?: string;
        /* padding */
        fill?: boolean;
    }

    let { title, children, footer, dismissable = true, onCancel, overlayClass = '', contentClass = '', head, role = 'dialog', describedby, trapFocus = true, escapeGuard, width, height, fill = false, ...rest }: Props = $props();

    let overlay = $state<HTMLElement | null>(null);
    let opener: HTMLElement | null = null;

    function stops(): HTMLElement[] {
        if (!overlay) return [];
        return [...overlay.querySelectorAll<HTMLElement>(FOCUSABLE)];
    }

    function onKeydown(event: KeyboardEvent): void {
        if (event.key === 'Escape') {
            event.stopPropagation();
            if (!dismissable) return;
            if (escapeGuard && !escapeGuard(event)) return;
            onCancel();
            return;
        }
        if (event.key !== 'Tab' || !trapFocus) return;
        const ring = stops();
        if (ring.length === 0) {
            event.preventDefault();
            return;
        }
        const first = ring[0] as HTMLElement;
        const last = ring[ring.length - 1] as HTMLElement;
        const active = document.activeElement as HTMLElement | null;
        if (event.shiftKey && (active === first || !overlay?.contains(active))) {
            event.preventDefault();
            last.focus();
            return;
        }
        if (!event.shiftKey && (active === last || !overlay?.contains(active))) {
            event.preventDefault();
            first.focus();
        }
    }

    onMount(() => {
        opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        if (overlay && !overlay.contains(document.activeElement)) {
            (stops()[0] ?? overlay).focus();
        }
        const reclaim = new MutationObserver(() => {
            if (overlay && !overlay.contains(document.activeElement)) (stops()[0] ?? overlay).focus();
        });
        if (overlay && trapFocus) reclaim.observe(overlay, { childList: true, subtree: true });
        return () => {
            reclaim.disconnect();
            if (opener && document.contains(opener)) opener.focus();
            opener = null;
        };
    });

    function onOverlayClick(event: MouseEvent): void {
        if (event.target !== event.currentTarget) return;
        if (!dismissable) return;
        onCancel();
    }
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<!-- svelte-ignore a11y_click_events_have_key_events -->
<div
    {...rest}
    bind:this={overlay}
    class={overlayClass ? `modal-overlay ${overlayClass}` : 'modal-overlay'}
    {role}
    aria-modal="true"
    aria-label={title}
    aria-describedby={describedby}
    tabindex="-1"
    onkeydown={onKeydown}
    onclick={onOverlayClick}
>
    <div
        class={[contentClass ? `modal-content ${contentClass}` : 'modal-content', fill && 'modal-content--fill']}
        style:width
        style:height
        style:max-width={width || height ? 'none' : undefined}
        data-oc-base
    >
        {#if head}{@render head()}{:else}<div class="modal-header">
            <span>&raquo; {title}</span>
            <IconButton label={t('modal.close')} variant="close" icon="close" iconSize={14} data-modal-close
                disabled={!dismissable} onclick={onCancel} />
        </div>{/if}
        <div class="modal-body">{@render children()}</div>
        {#if footer}<div class="modal-footer">{@render footer()}</div>{/if}
    </div>
</div>

<style>
    .modal-content--fill {
        display: flex;
        flex-direction: column;
        padding: 0;
        overflow: hidden;
        container: oc-head / inline-size;
    }

    .modal-content--fill .modal-body {
        display: flex;
        flex: 1 1 auto;
        flex-direction: column;
        min-height: 0;
        margin: 0;
        padding: 0;
        overflow: hidden;
    }

    .modal-header {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 12px;
    }
</style>
