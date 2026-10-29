
<script lang="ts">
    import Button from '../lib/base/Button.svelte';
    import type { AdminHost } from './admin-host.svelte.js';
    import { t } from './text.js';
    import { ADMIN_KEYS } from '../../../client/js/labels/admin.js';

    let { host }: { host: AdminHost } = $props();

    let address = $state('');
    let code = $state('');
</script>

<section class="admin-panel">
    <h2 class="admin-panel__heading">{t(ADMIN_KEYS.signinHeading)}</h2>

    {#if host.step === 'passkey'}
        <p class="admin-note">
            {host.hint === 'use_passkey'
                ? t(ADMIN_KEYS.signinPasskeyEnrolled)
                : t(ADMIN_KEYS.signinPasskeyHint)}
        </p>
        <div class="admin-form">
            <Button variant="confirm"
                disabled={host.busy}
                onclick={() => void host.signInPasskey()}
            >
                {host.busy ? t(ADMIN_KEYS.signinPasskeyWaiting) : t(ADMIN_KEYS.signinPasskeyAction)}
            </Button>
            <Button onclick={() => host.useEmail()}>
                {t(ADMIN_KEYS.signinEmailInstead)}
            </Button>
        </div>
    {:else if host.step === 'email'}
        <form
            class="admin-form"
            onsubmit={(event) => {
                event.preventDefault();
                void host.start(address);
            }}
        >
            <label class="admin-field" for="admin-email">
                {t(ADMIN_KEYS.signinEmailLabel)}
            </label>
            <input
                id="admin-email"
                class="admin-input"
                type="email"
                autocomplete="email"
                bind:value={address}
            />
            <Button variant="confirm" type="submit" disabled={host.busy}>
                {host.busy ? t(ADMIN_KEYS.signinSending) : t(ADMIN_KEYS.signinEmailAction)}
            </Button>
            {#if host.passkeyAvailable}
                <Button onclick={() => host.usePasskey()}>
                    {t(ADMIN_KEYS.signinPasskeyInstead)}
                </Button>
            {/if}
        </form>
    {:else}
        <p class="admin-note">
            {t(ADMIN_KEYS.signinSent, { destination: host.destination })}
        </p>
        <form
            class="admin-form"
            onsubmit={(event) => {
                event.preventDefault();
                void host.submitCode(code);
            }}
        >
            <label class="admin-field" for="admin-code">
                {t(ADMIN_KEYS.signinCodeLabel)}
            </label>
            <input
                id="admin-code"
                class="admin-input admin-input--code"
                type="text"
                inputmode="numeric"
                autocomplete="one-time-code"
                bind:value={code}
            />
            <Button variant="confirm" type="submit" disabled={host.busy}>
                {host.busy ? t(ADMIN_KEYS.signinChecking) : t(ADMIN_KEYS.signinCodeAction)}
            </Button>
            <Button onclick={() => host.restart()}>
                {t(ADMIN_KEYS.signinRestart)}
            </Button>
        </form>
    {/if}
</section>
