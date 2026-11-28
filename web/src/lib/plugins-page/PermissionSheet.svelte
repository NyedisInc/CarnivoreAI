
<script lang="ts">
    import Button from '../base/Button.svelte';
    import Checkbox from '../base/Checkbox.svelte';
    import type { Translate } from '../sessions/types';
    import { needsTick, type CplugUiSlotRow, type PermissionRow } from './cplugs-adapter';

    interface Props {
        rows: readonly PermissionRow[];
        uiSlots?: readonly CplugUiSlotRow[];
        missing: readonly string[];
        waiting: boolean;
        off?: boolean;
        consent?: boolean;
        warnings: readonly string[];
        busy?: boolean;
        onGrant: (ticks: string[], slotTicks?: string[]) => void;
        t: Translate;
    }

    const { rows, uiSlots = [], missing, waiting, off = false, consent = false, warnings, busy = false, onGrant, t }: Props = $props();

    let ticked = $state<Record<string, boolean>>({});
    let slotTicked = $state<Record<string, boolean>>({});
    const isMissing = (row: PermissionRow): boolean => missing.includes(row.name) || !row.granted;
    const pending = $derived(rows.filter(isMissing));
    const mustTick = $derived(pending.filter((r) => needsTick(r.risk)));
    const blocked = $derived(pending.some((r) => r.risk === 'never'));
    const pendingSlots = $derived(uiSlots.filter((s) => !s.granted));
    const mustTickSlots = $derived(pendingSlots.filter((s) => s.needs_tick || needsTick(s.risk)));
    const blockedSlots = $derived(pendingSlots.some((s) => s.risk === 'never'));
    const codeOnly = $derived(waiting && pending.length === 0 && pendingSlots.length === 0);
    const ready = $derived(
        !blocked &&
            !blockedSlots &&
            (codeOnly ||
                (mustTick.every((r) => ticked[r.name] === true) &&
                    mustTickSlots.every((s) => slotTicked[s.slot] === true))),
    );
    const granting = $derived(waiting || (off && consent && (pending.length > 0 || pendingSlots.length > 0)));
    const grantedCount = $derived(rows.length - pending.length);

    function riskTone(risk: CplugUiSlotRow['risk']): 'high' | undefined {
        return risk === 'high' || risk === 'never' ? 'high' : undefined;
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
                <span class="plp-tag" data-tone={riskTone(row.risk)}>{t(`plugins.page.risk.${row.risk}`)}</span>
                <span class="plp-tag" data-perm-granted={!gap} data-tone={gap ? (granting ? 'warn' : 'off') : 'ok'}>
                    {t(gap ? 'plugins.page.sheet.not_granted' : 'plugins.page.sheet.granted')}
                </span>
            </li>
        {:else}
            <li class="plp-row plp-row--empty">{t('plugins.page.fact.asks_nothing')}</li>
        {/each}
    </ul>
    {#if uiSlots.length > 0}
        <h3 class="pl-label">{t('plugins.page.sheet.ui_slots_heading')}</h3>
        <ul class="plp-rows" data-perm-ui-slots>
            {#each uiSlots as slot (slot.slot)}
                {@const gap = !slot.granted}
                <li class="plp-row" class:plp-row--missing={granting && gap} data-perm-slot-row={slot.slot} data-risk={slot.risk}>
                    {#if granting && gap && (slot.needs_tick || needsTick(slot.risk))}
                        <Checkbox
                            data-perm-slot-tick={slot.slot}
                            aria-label={t('plugins.page.sheet.tick_slot', { slot: slot.slot })}
                            checked={slotTicked[slot.slot] === true}
                            disabled={busy}
                            onchange={(e) => (slotTicked[slot.slot] = e.currentTarget.checked)}
                        />
                    {/if}
                    <span class="plp-row__main"
                        >{t('plugins.page.sheet.ui_slot_label', { slot: slot.slot, count: slot.count })}<span class="plp-row__sub">{`ui.slot:${slot.slot}`}</span><span
                            class="plp-row__sub"
                            data-perm-slot-reason>{slot.reason || t('plugins.page.sheet.no_reason')}</span
                        ></span
                    >
                    <span class="plp-tag" data-tone={riskTone(slot.risk)}>{t(`plugins.page.risk.${slot.risk}`)}</span>
                    <span class="plp-tag" data-perm-slot-granted={!gap} data-tone={gap ? (granting ? 'warn' : 'off') : 'ok'}>
                        {t(gap ? 'plugins.page.sheet.not_granted' : 'plugins.page.sheet.granted')}
                    </span>
                </li>
            {/each}
        </ul>
    {/if}
    {#if granting}
        <div class="plp-actions">
            <span class="plp-actions__note"
                >{codeOnly ? t('plugins.page.sheet.changed_note') : blocked || blockedSlots ? t('plugins.page.sheet.never') : t('plugins.page.sheet.low_note')}</span
            >
            <Button
                variant="confirm"
                data-cplug-grant
                title={t(codeOnly ? 'plugins.page.approve.title' : 'plugins.page.grant.title')}
                disabled={busy || !ready}
                onclick={() => {
                    if (uiSlots.length > 0) {
                        onGrant(
                            mustTick.map((r) => r.name),
                            mustTickSlots.map((s) => s.slot),
                        );
                    } else {
                        onGrant(mustTick.map((r) => r.name));
                    }
                }}
                >{codeOnly
                    ? t('plugins.page.approve')
                    : t(waiting ? 'plugins.page.grant' : 'plugins.page.grant.on', { count: pending.length + pendingSlots.length })}</Button
            >
        </div>
    {:else if off && (rows.length > 0 || uiSlots.length > 0)}
        <p class="plp-note">{t('plugins.page.sheet.off_note')}</p>
    {/if}
</section>
