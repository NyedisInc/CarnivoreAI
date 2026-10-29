
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import { needsTick, type PermissionRow } from './cplugs-adapter';

    interface Props {
        rows: readonly PermissionRow[];
        missing: readonly string[];
        waiting: boolean;
        off?: boolean;
        warnings: readonly string[];
        busy?: boolean;
        onGrant: (ticks: string[]) => void;
        t: Translate;
    }

    const { rows, missing, waiting, off = false, warnings, busy = false, onGrant, t }: Props = $props();

    let ticked = $state<Record<string, boolean>>({});
    const isMissing = (row: PermissionRow): boolean => missing.includes(row.name) || !row.granted;
    const pending = $derived(rows.filter(isMissing));
    const mustTick = $derived(pending.filter((r) => needsTick(r.risk)));
    const blocked = $derived(pending.some((r) => r.risk === 'never'));
    const ready = $derived(!blocked && pending.length > 0 && mustTick.every((r) => ticked[r.name] === true));
    const grantedCount = $derived(rows.length - pending.length);

    function riskTone(row: PermissionRow): 'high' | undefined {
        return row.risk === 'high' || row.risk === 'never' ? 'high' : undefined;
    }
</script>

<section class="plp-region" data-perm-sheet aria-label={t('plugins.page.sheet.title')}>
    <h3 class="pl-label">
        {t('plugins.page.sheet.asks')}
        {#if rows.length}<span class="plp-label__count" data-perm-count>{t('plugins.page.sheet.count', { granted: grantedCount, total: rows.length })}</span>{/if}
    </h3>
    {#each warnings as warning (warning)}
        <p class="plp-warn" data-perm-warning>{warning}</p>
    {/each}
    <ul class="plp-rows">
        {#each rows as row (row.name)}
            {@const gap = isMissing(row)}
            <li class="plp-row" class:plp-row--missing={waiting && gap} data-perm-row={row.name} data-risk={row.risk}>
                {#if waiting && gap && needsTick(row.risk)}
                    <input
                        type="checkbox"
                        data-perm-tick={row.name}
                        aria-label={t('plugins.page.sheet.tick', { name: row.label })}
                        checked={ticked[row.name] === true}
                        disabled={busy}
                        onchange={(e) => (ticked[row.name] = e.currentTarget.checked)}
                    />
                {/if}
                <span class="plp-row__main"
                    >{row.label}<span class="plp-row__sub">{row.name}</span><span class="plp-row__sub" data-perm-reason
                        >{row.reason || t('plugins.page.sheet.no_reason')}</span
                    ></span
                >
                <span class="plp-tag" data-tone={riskTone(row)}>{t(`plugins.page.risk.${row.risk}`)}</span>
                <span class="plp-tag" data-perm-granted={!gap} data-tone={gap ? (waiting ? 'warn' : 'off') : 'ok'}>
                    {t(gap ? 'plugins.page.sheet.not_granted' : 'plugins.page.sheet.granted')}
                </span>
            </li>
        {:else}
            <li class="plp-row plp-row--empty">{t('plugins.page.fact.asks_nothing')}</li>
        {/each}
    </ul>
    {#if waiting && pending.length}
        <div class="plp-actions">
            <span class="plp-actions__note">{blocked ? t('plugins.page.sheet.never') : t('plugins.page.sheet.low_note')}</span>
            <button
                type="button"
                class="modal-btn modal-btn-confirm"
                data-cplug-grant
                title={t('plugins.page.grant.title')}
                disabled={busy || !ready}
                onclick={() => onGrant(mustTick.map((r) => r.name))}>{t('plugins.page.grant', { count: pending.length })}</button
            >
        </div>
    {:else if off && rows.length}
        <p class="plp-note">{t('plugins.page.sheet.off_note')}</p>
    {/if}
</section>
