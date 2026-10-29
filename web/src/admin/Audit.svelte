
<script lang="ts">
    import Button from '../lib/base/Button.svelte';
    import Field from '../lib/base/Field.svelte';
    import type { CommunityHost } from './community-host.svelte.js';
    import { refusalMessage } from './admin.js';
    import { auditActor, auditReason, auditTarget, auditTime } from './moderation.js';
    import { hasKey, t } from './text.js';
    import { ADMIN_KEYS } from '../../../client/js/labels/admin.js';

    let { host }: { host: CommunityHost } = $props();

    let attempted = $state(false);
    $effect(() => {
        if (attempted || host.auditLoaded || host.busy) return;
        attempted = true;
        void host.loadAudit();
    });

    function actionText(action: string | undefined): string {
        const key = 'admin.audit.action.' + (action || '');
        return action && hasKey(key) ? t(key) : action || '';
    }

    function digestOf(detail: unknown): string {
        const sha = (detail as { report_sha256?: unknown } | null)?.report_sha256;
        return typeof sha === 'string' ? sha.slice(0, 12) : '';
    }

    const refusalText = $derived(refusalMessage(host.refusal, t));
</script>

<section class="admin-panel">
    <h2 class="admin-panel__heading">{t(ADMIN_KEYS.auditHeading)}</h2>

    {#if refusalText}
        <p class="admin-refusal" role="alert">{refusalText}</p>
    {/if}

    <label class="admin-field" for="audit-day">{t(ADMIN_KEYS.auditDayLabel)}</label>
    <Field id="audit-day" data-admin-grow type="date" value={host.day}
        oninput={(event) => host.setDay(event.currentTarget.value)} />
    <Button disabled={host.busy}
        onclick={() => void host.loadAudit()}>{t(ADMIN_KEYS.auditLoad)}</Button>

    {#if !host.auditLoaded}
        <p class="admin-note">{t(ADMIN_KEYS.loading)}</p>
    {:else if host.entries.length === 0}
        <p class="admin-note">{t(ADMIN_KEYS.auditEmpty)}</p>
    {:else}
        <ul class="admin-list">
            {#each host.entries as row, index (row.audit_id || index)}
                <li class="admin-list__row admin-audit">
                    <span class="admin-list__meta">{auditTime(row.at)}</span>
                    <span class="admin-list__name">{auditActor(row)}</span>
                    <span class="admin-list__name">{actionText(row.action)}</span>
                    <span class="admin-list__meta">{auditTarget(row)}</span>
                    {#if digestOf(row.detail)}
                        <span class="admin-list__meta">{t(ADMIN_KEYS.auditDigest, { sha: digestOf(row.detail) })}</span>
                    {/if}
                    {#if auditReason(row.detail)}
                        <span class="admin-audit__reason">{t(ADMIN_KEYS.auditReason, { reason: auditReason(row.detail) })}</span>
                    {/if}
                </li>
            {/each}
        </ul>
        {#if host.auditMore}
            <Button disabled={host.busy}
                onclick={() => void host.loadMoreAudit()}>{t(ADMIN_KEYS.auditMore)}</Button>
        {/if}
    {/if}
</section>
