
<script lang="ts">
    import type { AdminHost } from './admin-host.svelte.js';
    import { t } from './text.js';
    import { ADMIN_KEYS } from '../../../client/js/labels/admin.js';
    import Passkeys from './Passkeys.svelte';

    let { host }: { host: AdminHost } = $props();
</script>

<section class="admin-panel">
    <h2 class="admin-panel__heading">{t(ADMIN_KEYS.systemHeading)}</h2>
    {#if host.me}
        <p class="admin-note">
            {t(ADMIN_KEYS.systemAccount, {
                login: host.me.login,
                provider: host.me.provider,
            })}
        </p>
    {/if}
    <p class="admin-note">{t(ADMIN_KEYS.systemOrigin)}</p>
    <p class="admin-note">{t(ADMIN_KEYS.systemToken)}</p>
    <p class="admin-note">{t(ADMIN_KEYS.systemRefresh)}</p>
</section>
{#if host.me?.is_admin}
    <Passkeys {host} />
{/if}
