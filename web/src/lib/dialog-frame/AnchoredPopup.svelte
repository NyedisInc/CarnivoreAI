<!-- frame, and the -->
<script lang="ts">
    import { onMount, type Snippet } from 'svelte';
    import type { HTMLAttributes } from 'svelte/elements';
    import { isSheetWidth, placePanel } from '../dropdown/placement';

    const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

    interface Props extends Omit<HTMLAttributes<HTMLDivElement>, 'role' | 'class' | 'style' | 'children'> {
        label: string;
        role?: 'dialog' | 'alertdialog';
        class?: string;
        anchor?: HTMLElement | null;
        placement?: 'below' | 'manual';
        style?: string;
        onPlace?: () => void;
        topLayer?: boolean;
        initialFocus?: string;
        returnFocus?: boolean;
        dismissable?: boolean | (() => boolean);
        escape?: 'popup' | 'window' | 'document';
        outside?: 'bubble' | 'capture' | 'none';
        onClose: () => void;
        onEscape?: () => void;
        element?: HTMLElement | null;
        children: Snippet;
    }

    let {
        label,
        role = 'dialog',
        class: className = '',
        anchor = null,
        placement = 'below',
        style = undefined,
        onPlace,
        topLayer = false,
        initialFocus = '',
        returnFocus = true,
        dismissable = true,
        escape = 'popup',
        outside = 'bubble',
        onClose,
        onEscape,
        onkeydown: ownKeydown,
        element = $bindable(null),
        children,
        ...rest
    }: Props = $props();

    let below = $state('');

    function mayDismiss(): boolean {
        return typeof dismissable === 'function' ? dismissable() : dismissable;
    }

    function place(): void {
        if (placement === 'manual') {
            onPlace?.();
            return;
        }
        if (!element || !anchor || typeof window === 'undefined') return;
        const rect = anchor.getBoundingClientRect();
        const own = element.offsetWidth;
        below = placePanel(
            { top: rect.top, bottom: rect.bottom, left: rect.left, width: rect.width },
            { width: window.innerWidth, height: window.innerHeight },
            isSheetWidth(),
            (boxWidth) => Math.max(own, boxWidth),
        ).style;
    }

    function onKey(event: KeyboardEvent): void {
        if (event.key !== 'Escape') return;
        if (escape !== 'document') {
            event.preventDefault();
            event.stopPropagation();
        }
        if (!mayDismiss()) return;
        (onEscape ?? onClose)();
    }

    function onPopupKey(event: KeyboardEvent): void {
        if (escape === 'popup' && event.key === 'Escape') {
            onKey(event);
            return;
        }
        (ownKeydown as ((event: KeyboardEvent) => void) | null | undefined)?.(event);
    }

    function onPress(event: PointerEvent): void {
        const target = event.target as Node | null;
        if (!target || element?.contains(target) || anchor?.contains(target)) return;
        if (!mayDismiss()) return;
        onClose();
    }

    function focusTarget(): HTMLElement | null {
        if (!element || initialFocus === 'none') return null;
        if (initialFocus === 'self') return element;
        if (initialFocus) return element.querySelector<HTMLElement>(initialFocus);
        return element.querySelector<HTMLElement>(FOCUSABLE) ?? element;
    }

    onMount(() => {
        const el = element;
        if (!el) return;
        if (topLayer && !el.matches(':popover-open')) el.showPopover?.();
        place();
        focusTarget()?.focus();
        const listeners: Array<[EventTarget, string, EventListener, boolean]> = [];
        const listen = (target: EventTarget, type: string, fn: EventListener, capture: boolean): void => {
            target.addEventListener(type, fn, capture);
            listeners.push([target, type, fn, capture]);
        };
        listen(window, 'resize', place, false);
        listen(window, 'scroll', place, true);
        if (escape === 'window') listen(window, 'keydown', onKey as EventListener, false);
        if (escape === 'document') listen(document, 'keydown', onKey as EventListener, true);
        if (outside === 'bubble') listen(window, 'pointerdown', onPress as EventListener, false);
        if (outside === 'capture') listen(window, 'pointerdown', onPress as EventListener, true);
        const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => place());
        observer?.observe(el);
        return () => {
            observer?.disconnect();
            for (const [target, type, fn, capture] of listeners) target.removeEventListener(type, fn, capture);
            const active = document.activeElement;
            if (returnFocus && anchor && document.contains(anchor) && (!active || active === document.body || el.contains(active))) anchor.focus();
        };
    });
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<div
    {...rest}
    bind:this={element}
    class={className ? `oc-anchored popup-focus ${className}` : 'oc-anchored popup-focus'}
    {role}
    aria-label={label}
    popover={topLayer ? 'manual' : undefined}
    style={placement === 'manual' ? style : below || undefined}
    onkeydown={onPopupKey}
>
    {@render children()}
</div>

<style>
    @layer base {
        .oc-anchored {
            position: fixed;
            margin: 0;
            z-index: var(--oc-z-popover);
        }
    }
</style>
