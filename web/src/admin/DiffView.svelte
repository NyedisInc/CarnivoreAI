
<script lang="ts">
    import type { ReportDiff } from './admin.js';
    import { t } from './text.js';
    import { ADMIN_KEYS } from '../../../client/js/labels/admin.js';

    let { diff }: { diff: ReportDiff | undefined } = $props();

    const CHANGE_KEYS: Record<string, string> = {
        added: ADMIN_KEYS.diffChangeAdded,
        removed: ADMIN_KEYS.diffChangeRemoved,
        changed: ADMIN_KEYS.diffChangeChanged,
    };

    const changeLabel = (change: string): string => {
        const key = CHANGE_KEYS[change];
        return key ? t(key) : change;
    };
</script>

<section class="admin-report__block">
    <h3 class="admin-report__heading">{t(ADMIN_KEYS.diffHeading)}</h3>
    {#if !diff}
        <p class="admin-note">{t(ADMIN_KEYS.diffAbsent)}</p>
    {:else if diff.first_release}
        <p class="admin-note">{t(ADMIN_KEYS.diffFirst)}</p>
    {:else if diff.unavailable}
        <p class="admin-note">{t(ADMIN_KEYS.diffUnavailable)}</p>
    {:else}
        <p class="admin-list__meta">
            {t(ADMIN_KEYS.diffSummary, {
                version: diff.base_version || '',
                added: diff.added ?? 0,
                removed: diff.removed ?? 0,
                changed: diff.changed ?? 0,
                bytes: diff.bytes_delta ?? 0,
            })}
        </p>
        <ul class="admin-report__list">
            {#each diff.paths || [] as row (row.change + row.path)}
                <li class="admin-report__row admin-report__row--{row.change}">
                    {t(ADMIN_KEYS.diffRow, {
                        change: changeLabel(row.change),
                        path: row.path,
                    })}
                </li>
            {/each}
        </ul>
    {/if}
</section>
