
<script lang="ts">
    import { captureOpener, restoreOpenerFocus } from '../dialog-frame/opener-focus';
    import Page from '../../opscenter/ui/Page.svelte';
    import LogViewer from '../../opscenter/log/LogViewer.svelte';
    import { t } from '../i18n/index.svelte';

    let open = $state(false);
    let opener: HTMLElement | null = null;

    export function show(): void {
        if (open) return;
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
</script>

{#if open}
    <Page title={t('opscenter.log.page.title')} label={t('opscenter.log.page.label')} onClose={close} data-logs-page="">
        <div class="oc-page__body oc-lv-page">
            <LogViewer />
        </div>
    </Page>
{/if}
