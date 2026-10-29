<!-- hidden -->
<script lang="ts">
    import { captureOpener, restoreOpenerFocus } from '../dialog-frame/opener-focus';
    import Page from '../../opscenter/ui/Page.svelte';
    import { onContextMenu, onMenuKey } from '../../opscenter/layout-editor/empty-space-menu.svelte';
    import { t } from '../i18n/index.svelte';
    import WarRoomGrid from './WarRoomGrid.svelte';
    import { warroomAvailable } from './phone.svelte';

    let open = $state(false);
    let opener: HTMLElement | null = null;

    export function show(): void {
        if (open || !warroomAvailable()) return;
        opener = captureOpener();
        open = true;
    }

    export function close(): void {
        if (!open) return;
        open = false;
        restoreOpenerFocus(opener);
        opener = null;
    }

    export function isOpen(): boolean {
        return open;
    }

    $effect(() => {
        if (open && !warroomAvailable()) close();
    });
</script>

{#if open}
    <Page title={t('warroom.page.title')} bare onClose={close} data-warroom-page="">
        <div class="oc-page__body wr-body">
            {@render surface()}
        </div>
    </Page>
{/if}

{#snippet surface()}
    
    <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
    <div
        class="wr-surface"
        role="group"
        tabindex="0"
        aria-label={t('opscenter.empty_menu.label')}
        oncontextmenu={onContextMenu}
        onkeydown={(event) => onMenuKey(event, event.currentTarget)}
    >
        <WarRoomGrid />
    </div>
{/snippet}

<style>
    @layer components {
        .wr-body {
            grid-template-rows: minmax(0, 1fr);
        }

        .wr-surface {
            position: relative;
            min-width: 0;
            min-height: 0;
            overflow: hidden;
        }

        /* height: 100% min-height: 1 */
        .wr-surface :global(.oc-surface) {
            height: 100%;
            min-height: 0;
            overflow: hidden;
        }
    }
</style>
