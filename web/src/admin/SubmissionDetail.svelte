
<script lang="ts">
    import Button from '../lib/base/Button.svelte';
    import { untrack } from 'svelte';
    import {
        ApiRefusal, isLegacyPending, type SubmissionDetail, type SubmissionFile, type SubmissionRow,
    } from './admin.js';
    import type { AdminHost } from './admin-host.svelte.js';
    import ReportView from './ReportView.svelte';
    import FileView from './FileView.svelte';
    import { t } from './text.js';
    import { ADMIN_KEYS } from '../../../client/js/labels/admin.js';

    let { host, row }: { host: AdminHost; row: SubmissionRow } = $props();

    const id = $derived(row.submission_id);
    const api = $derived(host.api);
    const report = $derived(host.reports[row.submission_id]);
    const decidable = $derived(!isLegacyPending(row) && (row.status === 'pending' || row.status === 'gate_failed'));
    const regatable = $derived(row.gate_state === 'stuck' || row.gate_state === 'failed' || row.status === 'gate_failed');
    const canOverride = $derived(row.status === 'gate_failed' && row.overridable === true);
    const canRevoke = $derived(row.status === 'published');
    const revokeOpen = $derived(host.revoking === row.submission_id);
    const overrideOpen = $derived(host.overriding === row.submission_id);

    let detail = $state<SubmissionDetail | null>(null);
    let file = $state<SubmissionFile | null>(null);
    let loading = $state(true);
    let errorKey = $state('');

    function failure(error: unknown): string {
        const status = error instanceof ApiRefusal ? error.refusal.status : 0;
        if (status === 403) return ADMIN_KEYS.detailError403;
        if (status === 404) return ADMIN_KEYS.detailError404;
        if (status === 503) return ADMIN_KEYS.detailError503;
        return ADMIN_KEYS.detailError;
    }

    $effect(() => {
        const wanted = row.submission_id;
        const digest = row.report_sha256;
        if (digest && untrack(() => host.reports[wanted]?.report_sha256) !== digest) void host.loadReport(wanted);
    });

    $effect(() => {
        const wanted = id;
        loading = true;
        errorKey = '';
        file = null;
        api.submissionDetail(wanted).then(
            (body) => { if (wanted === id) { detail = body; loading = false; } },
            (error) => { if (wanted === id) { errorKey = failure(error); loading = false; } },
        );
    });

    async function view(path: string): Promise<void> {
        loading = true;
        errorKey = '';
        try {
            file = await api.submissionFile(id, path);
        } catch (error) {
            file = null;
            errorKey = failure(error);
        } finally {
            loading = false;
        }
    }
</script>

<div class="admin-detail">
    {#if loading}
        <p class="admin-note">{t(ADMIN_KEYS.loading)}</p>
    {/if}
    {#if errorKey}
        <p class="admin-note" role="alert">{t(errorKey)}</p>
    {/if}
    {#if detail}
        {#if detail.submitter}
            <p class="admin-list__meta">
                {t(ADMIN_KEYS.detailSubmitter, {
                    handle: detail.submitter.handle,
                    provider: detail.submitter.provider,
                    email: detail.submitter.email,
                })}
            </p>
            <p class="admin-list__meta">
                {detail.submitter.account_age_days === null
                    ? t(ADMIN_KEYS.detailAgeUnknown)
                    : t(ADMIN_KEYS.detailAge, { days: detail.submitter.account_age_days })}
                {detail.submitter.prior_approvals === null
                    ? ''
                    : ', ' + t(ADMIN_KEYS.detailPrior, { count: detail.submitter.prior_approvals })}
            </p>
        {/if}
        {#if report}
            <ReportView answer={report} />
        {/if}
        <h3 class="admin-list__name">{t(ADMIN_KEYS.detailFiles)}</h3>
        {#if !detail.files || detail.files.length === 0}
            <p class="admin-note">{t(ADMIN_KEYS.detailNoFiles)}</p>
        {:else}
            <ul class="admin-list">
                {#each detail.files as entry (entry.path)}
                    <li class="admin-list__row">
                        <Button onclick={() => void view(entry.path)}>
                            {t(ADMIN_KEYS.detailViewFile, { path: entry.path, size: entry.size })}
                        </Button>
                    </li>
                {/each}
            </ul>
        {/if}
        {#if file}
            <FileView {file} />
        {/if}
    {/if}

    {#if row.status === 'revoked'}
        <p class="admin-note">{t(ADMIN_KEYS.detailRevoked, { at: row.revoked_at || '', reason: row.revocation_reason || '' })}</p>
    {/if}

    {#if canRevoke}
        <div class="admin-actionbar" role="group" aria-label={t(ADMIN_KEYS.actionsLabel)}>
            <label class="admin-field" for={'revoke-' + row.submission_id}>{t(ADMIN_KEYS.revokeLabel)}</label>
            <input id={'revoke-' + row.submission_id} class="admin-input" type="text" maxlength="500"
                value={revokeOpen ? host.revokeReason : ''}
                oninput={(event) => host.setRevokeReason(row.submission_id, event.currentTarget.value)} />
            <Button variant="danger"
                disabled={host.busy || !revokeOpen || !host.revokeReason.trim()}
                onclick={() => void host.confirmRevoke()}>
                {t(ADMIN_KEYS.revokeConfirm)}
            </Button>
        </div>
    {/if}

    {#if decidable}
        <div class="admin-actionbar" role="group" aria-label={t(ADMIN_KEYS.actionsLabel)}>
            {#if host.rejecting === row.submission_id}
                <label class="admin-field" for={'reason-' + row.submission_id}>{t(ADMIN_KEYS.queueRejectLabel)}</label>
                <input id={'reason-' + row.submission_id} class="admin-input" type="text" maxlength="500"
                    value={host.rejectReason}
                    oninput={(event) => host.setRejectReason(event.currentTarget.value)} />
                <Button variant="danger" onclick={() => void host.confirmReject()}>
                    {t(ADMIN_KEYS.queueRejectConfirm)}
                </Button>
                <Button onclick={() => host.cancelReject()}>
                    {t(ADMIN_KEYS.queueRejectCancel)}
                </Button>
            {:else}
                {#if row.gate_state === 'awaiting_approval'}
                    <Button variant="confirm" disabled={!report || host.busy}
                        onclick={() => void host.approve(row.submission_id)}>
                        {t(ADMIN_KEYS.queueActionApprove)}
                    </Button>
                {/if}
                {#if canOverride}
                    <label class="admin-field" for={'override-' + row.submission_id}>{t(ADMIN_KEYS.overrideLabel)}</label>
                    <input id={'override-' + row.submission_id} class="admin-input" type="text" maxlength="500"
                        value={overrideOpen ? host.overrideReason : ''}
                        oninput={(event) => {
                            if (!overrideOpen) host.beginOverride(row.submission_id);
                            host.setOverrideReason(event.currentTarget.value);
                        }} />
                    <Button variant="confirm"
                        disabled={!report || host.busy || !overrideOpen || !host.overrideReason.trim()}
                        onclick={() => void host.confirmOverride()}>
                        {t(ADMIN_KEYS.overrideConfirm)}
                    </Button>
                {/if}
                {#if regatable}
                    <Button disabled={host.busy}
                        onclick={() => void host.regate(row.submission_id)}>
                        {t(ADMIN_KEYS.actionRegate)}
                    </Button>
                {/if}
                <Button variant="danger" onclick={() => host.beginReject(row.submission_id)}>
                    {t(ADMIN_KEYS.queueActionReject)}
                </Button>
            {/if}
        </div>
    {/if}
</div>
