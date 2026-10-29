
<script lang="ts">
    import { loadOnce } from './load-once.svelte.js';
    import Button from '../lib/base/Button.svelte';
    import type { AdminHost } from './admin-host.svelte.js';
    import type { CommunityHost } from './community-host.svelte.js';
    import { ApiRefusal, seenAtText, type AdminApi, type UserRow } from './admin.js';
    import { exportNewsList } from './funnel.js';
    import { t } from './text.js';
    import { ADMIN_KEYS } from '../../../client/js/labels/admin.js';

    let { host, community, api }: { host: AdminHost; community: CommunityHost; api: AdminApi } = $props();

    let exportFailed = $state(false);

    /* nothing was exported. */
    async function exportNews(): Promise<void> {
        exportFailed = false;
        try {
            await exportNewsList(api, document);
        } catch (error) {
            if (!(error instanceof ApiRefusal)) throw error;
            exportFailed = true;
        }
    }

    loadOnce(() => !host.usersLoaded && !host.busy, () => host.loadUsers(false));

    function standingKey(row: UserRow): string {
        if (row.disabled === true) return ADMIN_KEYS.usersStandingDisabled;
        if (row.is_admin === true) return ADMIN_KEYS.usersStandingAdmin;
        return ADMIN_KEYS.usersStandingActive;
    }
</script>

<section class="admin-panel">
    <h2 class="admin-panel__heading">{t(ADMIN_KEYS.usersHeading)}</h2>

    {#if host.usersLoaded && host.users.length === 0}
        <p class="admin-note">{t(ADMIN_KEYS.usersEmpty)}</p>
    {:else if !host.usersLoaded}
        <p class="admin-note">{t(ADMIN_KEYS.loading)}</p>
    {:else}
        <table class="admin-table">
            <thead>
                <tr>
                    <th scope="col">{t(ADMIN_KEYS.usersColumnLogin)}</th>
                    <th scope="col">{t(ADMIN_KEYS.usersColumnProvider)}</th>
                    <th scope="col">{t(ADMIN_KEYS.usersColumnSeen)}</th>
                    <th scope="col">{t(ADMIN_KEYS.usersColumnStanding)}</th>
                    <th scope="col">{t(ADMIN_KEYS.usersColumnNews)}</th>
                    <th scope="col"></th>
                </tr>
            </thead>
            <tbody>
                {#each host.users as row (row.user_id)}
                    <tr>
                        <td>{row.login || row.email || row.user_id}</td>
                        <td>{row.provider || ''}</td>
                        <td>{seenAtText(row.seen_at) || t(ADMIN_KEYS.usersSeenNever)}</td>
                        <td>{t(standingKey(row))}</td>
                        <td>{row.news_opt_in === true ? t(ADMIN_KEYS.usersNewsYes) : t(ADMIN_KEYS.usersNewsNo)}</td>
                        <td class="admin-table__actions">
                            {#if host.mayChange(row)}
                                <Button variant={host.standingFor(row) !== 'enable' ? 'danger' : 'secondary'}
                                    onclick={() => void host.toggleStanding(row)}
                                >
                                    {host.standingFor(row) === 'enable'
                                        ? t(ADMIN_KEYS.usersActionEnable)
                                        : t(ADMIN_KEYS.usersActionDisable)}
                                </Button>
                                <Button
                                    onclick={() => void community.loadActivity(row.user_id)}
                                >
                                    {t(ADMIN_KEYS.usersActionActivity)}
                                </Button>
                                <Button
                                    onclick={() => void host.toggleAdmin(row)}
                                >
                                    {host.adminFor(row) === 'revoke'
                                        ? t(ADMIN_KEYS.usersActionRevoke)
                                        : t(ADMIN_KEYS.usersActionGrant)}
                                </Button>
                            {:else}
                                <span class="admin-tag">{t(ADMIN_KEYS.usersSelf)}</span>
                            {/if}
                        </td>
                    </tr>
                    {#if host.disabling === row.user_id}
                        <tr>
                            <td colspan="6">
                                <label class="admin-field" for={'disable-' + row.user_id}>
                                    {t(ADMIN_KEYS.usersDisableReasonLabel)}
                                </label>
                                <input
                                    id={'disable-' + row.user_id}
                                    class="admin-input"
                                    type="text"
                                    maxlength="200"
                                    value={host.disableReason}
                                    oninput={(event) => host.setDisableReason(event.currentTarget.value)}
                                />
                                <Button variant="danger"
                                    onclick={() => void host.confirmDisable()}>
                                    {t(ADMIN_KEYS.usersDisableConfirm)}
                                </Button>
                                <Button
                                    onclick={() => host.cancelDisable()}>
                                    {t(ADMIN_KEYS.usersDisableCancel)}
                                </Button>
                            </td>
                        </tr>
                    {/if}
                {/each}
            </tbody>
        </table>

        <Button onclick={() => void exportNews()}>
            {t(ADMIN_KEYS.usersExportNews)}
        </Button>
        {#if exportFailed}
            <p class="admin-refusal" role="alert">{t(ADMIN_KEYS.usersExportFailed)}</p>
        {/if}

        {#if community.activity}
            {@const view = community.activity}
            <h3 class="admin-list__name">
                {t(ADMIN_KEYS.usersActivityHeading, { handle: view.handle || view.user_id })}
            </h3>
            <p class="admin-list__meta">{t(ADMIN_KEYS.usersActivitySessions, { count: view.sessions_count })}</p>
            <p class="admin-list__meta">{t(ADMIN_KEYS.usersActivityComments)}</p>
            <ul class="admin-list">
                {#each view.comments as c (c.item_id + '/' + c.comment_id)}
                    <li class="admin-list__row">
                        <p class="admin-list__meta">{c.item_id} ({c.status})</p>
                        <p class="admin-note-text">{c.body}</p>
                    </li>
                {/each}
            </ul>
            <p class="admin-list__meta">{t(ADMIN_KEYS.usersActivityReviews)}</p>
            {#if view.reviews === null}
                <p class="admin-note">{t(ADMIN_KEYS.usersActivityUnavailable)}</p>
            {:else}
                <ul class="admin-list">
                    {#each view.reviews as r, i (r.review_ref || i)}
                        <li class="admin-list__row">
                            <p class="admin-note-text">{r.stars ?? ''} {r.text ?? ''}</p>
                        </li>
                    {/each}
                </ul>
            {/if}
            <p class="admin-list__meta">{t(ADMIN_KEYS.usersActivitySubmissions)}</p>
            <ul class="admin-list">
                {#each view.submissions as s, i (s.submission_id || i)}
                    <li class="admin-list__row">
                        <p class="admin-list__meta">{s.name || s.submission_id} ({s.status})</p>
                    </li>
                {/each}
            </ul>
            <Button onclick={() => community.closeActivity()}>
                {t(ADMIN_KEYS.usersActivityClose)}
            </Button>
        {/if}

        {#if host.usersCursor}
            <Button
                disabled={host.busy}
                onclick={() => void host.loadUsers(true)}
            >
                {t(ADMIN_KEYS.usersMore)}
            </Button>
        {/if}
    {/if}
</section>
