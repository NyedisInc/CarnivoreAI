<!-- passkey sign in -->
<script lang="ts">
    import { loadOnce } from './load-once.svelte.js';
    import Button from '../lib/base/Button.svelte';
    import Field from '../lib/base/Field.svelte';
    import type { AdminHost } from './admin-host.svelte.js';
    import { t } from './text.js';
    import { ADMIN_KEYS } from '../../../client/js/labels/admin.js';

    let { host }: { host: AdminHost } = $props();
    let label = $state('');

    loadOnce(() => true, () => host.pk.load());

    function when(seconds: number): string {
        return new Date(seconds * 1000).toLocaleDateString();
    }
</script>

{#if host.pk.configured}
    <section class="admin-panel">
        <h2 class="admin-panel__heading">{t(ADMIN_KEYS.passkeysHeading)}</h2>
        {#if host.pk.items.length === 0}
            <p class="admin-note">{t(ADMIN_KEYS.passkeysListHint)}</p>
        {:else}
            <ul class="admin-list">
                {#each host.pk.items as item (item.id)}
                    <li class="admin-list__row">
                        <p class="admin-list__name">{item.label}</p>
                        <p class="admin-list__meta">
                            {t(ADMIN_KEYS.passkeysCreated, { when: when(item.created_at) })}
                            ·
                            {item.last_used_at
                                ? t(ADMIN_KEYS.passkeysUsed, { when: when(item.last_used_at) })
                                : t(ADMIN_KEYS.passkeysNever)}
                            ·
                            {item.synced ? t(ADMIN_KEYS.passkeysSynced) : t(ADMIN_KEYS.passkeysDevice)}
                        </p>
                        <Button variant="danger"
                            disabled={host.busy}
                            onclick={() => void host.pk.remove(item.id)}
                        >
                            {t(ADMIN_KEYS.passkeysRemove)}
                        </Button>
                    </li>
                {/each}
            </ul>
        {/if}
        {#if host.pk.enrolled}
            <form
                class="admin-form"
                onsubmit={(event) => {
                    event.preventDefault();
                    void host.pk.enroll('add', '', label).then((ok) => {
                        if (ok) label = '';
                    });
                }}
            >
                <label class="admin-field" for="admin-add-label">{t(ADMIN_KEYS.passkeysAddLabel)}</label>
                <Field
                    id="admin-add-label" data-admin-grow
                    maxlength={40}
                    autocomplete="off"
                    bind:value={label}
                />
                <Button variant="confirm" type="submit" disabled={host.busy}>
                    {t(ADMIN_KEYS.passkeysAddAction)}
                </Button>
            </form>
        {/if}
    </section>
{/if}
