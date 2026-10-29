
<script lang="ts">
    import Button from '../base/Button.svelte';
    import Checkbox from '../base/Checkbox.svelte';
    import type { Translate } from '../sessions/types';
    import { needsTick, type PermissionRow } from './cplugs-adapter';

    interface Props {
        rows: readonly PermissionRow[];
        missing: readonly string[];
        waiting: boolean;
        off?: boolean;
        consent?: boolean;
        warnings: readonly string[];
        busy?: boolean;
        onGrant: (ticks: string[]) => void;
        t: Translate;
    }

    const { rows, missing, waiting, off = false, consent = false, warnings, busy = false, onGrant, t }: Props = $props();

    let ticked = $state<Record<string, boolean>>({});
    const isMissing = (row: PermissionRow): boolean => missing.includes(row.name) || !row.granted;
    const pending = $derived(rows.filter(isMissing));
    const mustTick = $derived(pending.filter((r) => needsTick(r.risk)));
    const blocked = $derived(pending.some((r) => r.risk === 'never'));
    const codeOnly = $derived(waiting && pending.length === 0);
    const ready = $derived(!blocked && (codeOnly || mustTick.every((r) => ticked[r.name] === true)));
    const granting = $derived(waiting || (off && consent && pending.length > 0));
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
            <li class="plp-row" class:plp-row--missing={granting && gap} data-perm-row={row.name} data-risk={row.risk}>
                {#if granting && gap && needsTick(row.risk)}
                    <Checkbox
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
                <span class="plp-tag" data-perm-granted={!gap} data-tone={gap ? (granting ? 'warn' : 'off') : 'ok'}>
                    {t(gap ? 'plugins.page.sheet.not_granted' : 'plugins.page.sheet.granted')}
                </span>
            </li>
        {:else}
            <li class="plp-row plp-row--empty">{t('plugins.page.fact.asks_nothing')}</li>
        {/each}
    </ul>
    {#if granting}
        <div class="plp-actions">
            <span class="plp-actions__note"
                >{codeOnly ? t('plugins.page.sheet.changed_note') : blocked ? t('plugins.page.sheet.never') : t('plugins.page.sheet.low_note')}</span
            >
            <Button
                variant="confirm"
                data-cplug-grant
                title={t(codeOnly ? 'plugins.page.approve.title' : 'plugins.page.grant.title')}
                disabled={busy || !ready}
                onclick={() => onGrant(mustTick.map((r) => r.name))}>{codeOnly ? t('plugins.page.approve') : t(waiting ? 'plugins.page.grant' : 'plugins.page.grant.on', { count: pending.length })}</Button
            >
        </div>
    {:else if off && rows.length}
        <p class="plp-note">{t('plugins.page.sheet.off_note')}</p>
    {/if}
</section>
