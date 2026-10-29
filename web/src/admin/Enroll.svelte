
<script lang="ts">
    import Button from '../lib/base/Button.svelte';
    import type { AdminHost } from './admin-host.svelte.js';
    import { t } from './text.js';
    import { ADMIN_KEYS } from '../../../client/js/labels/admin.js';

    let { host }: { host: AdminHost } = $props();

    let code = $state('');
    let label = $state('');
</script>

<section class="admin-panel">
    <h2 class="admin-panel__heading">{t(ADMIN_KEYS.enrollHeading)}</h2>
    <p class="admin-note">{t(ADMIN_KEYS.enrollNote)}</p>
    <form
        class="admin-form"
        onsubmit={(event) => {
            event.preventDefault();
            void host.pk.enroll('first', code, label);
        }}
    >
        <label class="admin-field" for="admin-enrol-code">{t(ADMIN_KEYS.enrollCodeLabel)}</label>
        <input
            id="admin-enrol-code"
            class="admin-input admin-input--code"
            type="text"
            autocomplete="off"
            bind:value={code}
        />
        <label class="admin-field" for="admin-enrol-label">{t(ADMIN_KEYS.enrollLabelLabel)}</label>
        <input
            id="admin-enrol-label"
            class="admin-input"
            type="text"
            maxlength="40"
            autocomplete="off"
            bind:value={label}
        />
        <Button variant="confirm" type="submit" disabled={host.busy}>
            {host.busy ? t(ADMIN_KEYS.enrollWorking) : t(ADMIN_KEYS.enrollAction)}
        </Button>
    </form>
</section>
