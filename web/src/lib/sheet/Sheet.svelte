
<script lang="ts">
    import type { Snippet } from 'svelte';
    import type { ClassValue, HTMLAttributes } from 'svelte/elements';

    export type SheetPlace = 'page' | 'column' | 'float';

    interface Props extends Omit<HTMLAttributes<HTMLElement>, 'class' | 'children'> {
        place: SheetPlace;
        tag?: 'aside' | 'div' | 'section';
        open?: boolean;
        phone?: boolean;
        folded?: boolean;
        docked?: boolean;
        width?: string;
        el?: HTMLElement | null;
        class?: ClassValue;
        children: Snippet;
    }

    let {
        place,
        tag = 'aside',
        open = true,
        phone = true,
        folded = false,
        docked = false,
        width,
        el = $bindable(null),
        class: className,
        children,
        ...rest
    }: Props = $props();
</script>

<svelte:element
    this={tag}
    bind:this={el}
    {...rest}
    class={['oc-sheet', className]}
    style:--sheet-w={width}
    data-sheet-place={place}
    data-sheet={open ? 'open' : 'closed'}
    data-sheet-phone={phone ? '' : undefined}
    data-sheet-folded={folded ? '' : undefined}
    data-sheet-docked={docked ? '' : undefined}
>
    {@render children()}
</svelte:element>

<style>
    @layer base {
        .oc-sheet {
            --_sheet-edge: calc(-1 * var(--oc-border, 1px)) 0 0 0 var(--oc-line-rule);
            --_sheet-soft: calc(-1 * var(--oc-space-3)) 0 var(--oc-space-5) calc(-1 * var(--oc-space-4)) var(--oc-backdrop);
            display: flex;
            flex-direction: column;
            min-width: 0;
            min-height: 0;
            max-width: 100%;
            color: var(--oc-text-primary);
            font-family: var(--font-mono);
            outline: none;
        }

        .oc-sheet[data-sheet-place='page'] {
            position: absolute;
            top: 0;
            right: 0;
            bottom: 0;
            z-index: var(--oc-z-sheet);
            width: var(--sheet-w, var(--oc-sheet-w));
            background: var(--oc-ground-panel);
            box-shadow: var(--_sheet-edge), var(--_sheet-soft);
            animation: oc-sheet-in var(--oc-motion) ease-out;
        }

        .oc-sheet[data-sheet-place='float'] {
            position: fixed;
            top: calc(var(--oc-topbar) + var(--oc-space-0-5));
            right: calc(var(--oc-free-right, 0px) + var(--oc-space-3));
            bottom: calc(var(--oc-free-bottom, 0px) + var(--oc-space-3));
            z-index: var(--oc-z-sheet);
            width: var(--sheet-w, var(--oc-sheet-w));
            background: var(--oc-ground-panel);
            border-radius: var(--oc-radius);
            box-shadow: 0 0 0 var(--oc-border, 1px) var(--oc-line-panel), var(--_sheet-soft);
        }

        .oc-sheet[data-sheet-place='float'][data-sheet-folded] {
            bottom: auto;
        }

        .oc-sheet[data-sheet-docked] {
            position: static;
            z-index: auto;
            flex: 1 1 auto;
            width: auto;
            border-radius: 0;
            box-shadow: none;
            animation: none;
        }

        @keyframes oc-sheet-in {
            from {
                transform: translateX(100%);
            }
            to {
                transform: none;
            }
        }

        @media (max-width: 700px) {
            .oc-sheet[data-sheet-phone] {
                position: fixed;
                inset: max(var(--overlay-top, 0px), env(safe-area-inset-top, 0px)) 0 0 0;
                z-index: var(--oc-z-sheet);
                width: 100%;
                border-radius: 0;
                background: var(--oc-ground-page);
                box-shadow: none;
                animation: oc-sheet-in var(--oc-motion) ease-out;
            }

            .oc-sheet[data-sheet-phone][data-sheet='closed'] {
                display: none;
            }
        }

        @media (prefers-reduced-motion: reduce) {
            .oc-sheet[data-sheet-place],
            .oc-sheet[data-sheet-phone] {
                animation: none;
            }
        }
    }
</style>
