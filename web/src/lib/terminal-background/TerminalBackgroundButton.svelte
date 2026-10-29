
<script lang="ts">
    import AnchoredPopup from '../dialog-frame/AnchoredPopup.svelte';
    import { t } from '../i18n/index.svelte';
    import TerminalBackgroundPanel from './TerminalBackgroundPanel.svelte';

    let { sessionName, palette, getPalette, asMenuItem = false, headless = false }: {
        sessionName?: string | null; palette?: Record<string, string>;
        getPalette?: () => Record<string, string> | undefined;
        asMenuItem?: boolean;
        headless?: boolean;
    } = $props();
    let anchorEl: HTMLElement | null = $state(null);
    let openedPalette = $state<Record<string, string> | undefined>(undefined);

    interface AnchorPopoverApi {
        place(el: HTMLElement, anchor: HTMLElement): { left: number; top: number };
    }

    let open = $state(false);
    let buttonEl: HTMLButtonElement | null = $state(null);
    let popoverEl: HTMLElement | null = $state(null);

    function position(): void {
        const anchor = (globalThis as { AnchorPopover?: AnchorPopoverApi }).AnchorPopover;
        const at = buttonEl ?? anchorEl;
        if (!anchor || !popoverEl || !at) return;
        anchor.place(popoverEl, at);
    }

    function close(): void {
        if (!open) return;
        open = false;
        (buttonEl ?? anchorEl)?.focus();
    }

    function toggle(): void {
        if (open) {
            close();
            return;
        }
        openedPalette = getPalette?.() ?? palette;
        open = true;
    }
    export function toggleAt(anchor: HTMLElement): void {
        anchorEl = anchor;
        toggle();
    }
</script>

{#if !headless}
<button data-base-exempt="a terminal bar key (or menu item) drawn by the bar, with a picture glyph"
    bind:this={buttonEl}
    class="tbg-open"
    class:tbg-menuitem={asMenuItem}
    type="button"
    role={asMenuItem ? 'menuitem' : undefined}
    aria-haspopup="dialog"
    aria-expanded={open}
    aria-label={t('terminal.background.open')}
    title={asMenuItem ? undefined : t('terminal.background.open')}
    onclick={toggle}
>
    
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <rect
            x="2.25"
            y="3.25"
            width="11.5"
            height="9.5"
            rx="1.5"
            stroke="currentColor"
            stroke-width="1.5"
        />
        <path
            d="M2.75 10.5 6 7.5l2.5 2.25L10.5 8l2.75 2.5"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linecap="round"
            stroke-linejoin="round"
        />
        <circle cx="10" cy="6" r="1" fill="currentColor" />
    </svg>
    {#if asMenuItem}<span class="tbg-menuitem-label">{t('terminal.background.open')}</span>{/if}
</button>
{/if}

{#if open}
    
    <AnchoredPopup
        bind:element={popoverEl}
        class="tbg-pop"
        topLayer
        label={t('terminal.background.open')}
        anchor={buttonEl ?? anchorEl}
        placement="manual"
        onPlace={position}
        initialFocus="none"
        escape="document"
        outside="capture"
        onClose={close}
    >
        <TerminalBackgroundPanel {sessionName} palette={openedPalette} />
    </AnchoredPopup>
{/if}

<style>
  @layer components {
        .tbg-open {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            flex-shrink: 0;
            box-sizing: border-box;
            position: relative;
            width: 22px;
            height: 22px;
            border: none;
            border-radius: 4px;
            margin: 0 2px;
            background: transparent;
            padding: 0;
            cursor: pointer;
            color: var(--color-fg-muted);
            transition: color 120ms ease, background 120ms ease;
        }

        .tbg-open svg {
            width: 16px;
            height: 16px;
            display: block;
            flex-shrink: 0;
        }

        .tbg-open:hover,
        .tbg-open:focus-visible {
            color: var(--color-accent);
            background: var(--color-accent-bg);
            outline: none;
        }

        .tbg-open:focus-visible {
            box-shadow: inset 0 0 0 1px var(--color-accent);
        }

        .tbg-open[aria-expanded='true'] {
            color: var(--color-accent);
            background: var(--color-accent-bg);
        }

        @media (pointer: coarse) {
            .tbg-open:not(.tbg-menuitem) {
                width: 44px;
                height: 44px;
                margin: -11px 2px;
            }
        }

        .tbg-menuitem {
            width: 100%;
            height: auto;
            justify-content: flex-start;
            gap: var(--oc-space-2);
            margin: 0;
            padding: 6px var(--oc-space-2);
            border-radius: var(--oc-radius-sm);
            color: var(--oc-text-secondary);
            font: inherit;
        }

        .tbg-menuitem:hover,
        .tbg-menuitem:focus-visible {
            color: var(--oc-text-bright);
            background: var(--oc-ground-hover);
            box-shadow: none;
        }

        .tbg-menuitem[aria-expanded='true'] {
            color: var(--oc-text-bright);
            background: var(--oc-ground-hover);
        }

        .tbg-menuitem-label {
            font-size: var(--oc-fs-label);
        }

        :global(.tbg-pop) {
            position: fixed;
            inset: auto;
            margin: 0;
            left: 0;
            top: 0;
            z-index: 60;
            width: 260px;
            max-width: calc(100vw - 16px);
            border-radius: var(--oc-radius-sm);
        }

        :global(.tbg-pop .tbg) {
            border-top: none;
        }
  }
</style>
