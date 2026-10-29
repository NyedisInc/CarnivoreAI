
<script lang="ts">
    import { captureOpener, restoreOpenerFocus } from '../dialog-frame/opener-focus';
    import ManagerFrame from '../manager-frame/ManagerFrame.svelte';
    import type { CatalogHost } from '../catalog/catalog';
    import { t as appT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import type { AccountPageHost } from './account-page-host';
    import AccountBody from './AccountBody.svelte';

    interface Props {
        host?: CatalogHost;
        account?: AccountPageHost;
        t?: Translate;
        embedded?: boolean;
    }

    const { host, account, t = appT, embedded = false }: Props = $props();

    // svelte-ignore state_referenced_locally
    let open = $state(embedded);
    let opener: HTMLElement | null = null;
    let query = $state('');

    export function show(): void {
        if (!open) {
            opener = captureOpener();
            open = true;
        }
    }

    export function close(): void {
        if (!open || embedded) return;
        open = false;
        restoreOpenerFocus(opener);
        opener = null;
    }

    export function isOpen(): boolean {
        return open;
    }
</script>

{#if open}
    <ManagerFrame
        title={t('account.page.title')}
        label={t('account.page.label')}
        items={[]}
        status={{ kind: 'ready' }}
        {query}
        onQuery={(next) => (query = next)}
        searchable={false}
        showCount={false}
        onClose={embedded ? undefined : close}
        {embedded}
        {t}
    >
        {#snippet body()}
            <AccountBody {host} {account} {t} />
        {/snippet}
    </ManagerFrame>
{/if}
