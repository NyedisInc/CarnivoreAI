
<script lang="ts">
    import { KIND_KEYS } from '../../../../client/js/labels/catalog-kind.js';
    import type { Translate } from '../sessions/types';
    import type { ModReport } from './types';

    interface Props {
        report: ModReport | null;
        flaggedNeeded: boolean;
        groups: readonly string[];
        trust: boolean;
        flagged: boolean;
        busy: boolean;
        t: Translate;
        onTrust: (next: boolean) => void;
        onFlagged: (next: boolean) => void;
    }

    const { report, flaggedNeeded, groups, trust, flagged, busy, t, onTrust, onFlagged }: Props = $props();

    const hooks = $derived(report?.hooks ?? []);
    const calls = $derived(report?.calls ?? []);
    const gating = $derived(report?.gating ?? []);
    const notes = $derived(report?.notes_raw ?? []);
    const empty = $derived(!report || (hooks.length === 0 && calls.length === 0 && notes.length === 0));

    function spends(call: string): boolean {
        return call.startsWith('$.model.');
    }
</script>

<div class="modfacts">
    <p class="modfacts__trust" role="note">{t(KIND_KEYS.modTrust)}</p>
    <p class="modfacts__note">{t(KIND_KEYS.modCallsNote)}</p>

    {#if empty}
        <p class="modfacts__note" role="status">{t(KIND_KEYS.modNoReport)}</p>
    {/if}

    {#if hooks.length}
        <p class="modfacts__label">{t(KIND_KEYS.modHooks)}</p>
        {#each hooks as entry}
            <p class="modfacts__module">{entry.module}</p>
            <ul class="modfacts__list">
                {#each entry.events as event}
                    <li class="modfacts__item">{event}</li>
                {/each}
            </ul>
        {/each}
    {/if}

    {#if calls.length}
        <p class="modfacts__label">{t(KIND_KEYS.modCalls)}</p>
        {#each calls as entry}
            <p class="modfacts__module">{entry.module}</p>
            <ul class="modfacts__list">
                {#each entry.calls as call}
                    <li class="modfacts__item" class:modfacts__item--spend={spends(call)}>
                        {call}{#if spends(call)} <span class="modfacts__spend">{t(KIND_KEYS.modSpendsUsage)}</span>{/if}
                    </li>
                {/each}
            </ul>
        {/each}
    {/if}

    {#if gating.length}
        <p class="modfacts__label">{t(KIND_KEYS.modGating)}</p>
        <ul class="modfacts__list">
            {#each gating as gate}
                <li class="modfacts__item">
                    {gate.pattern} {gate.hook}{#if !gate.has_catch} <span class="modfacts__spend">{t(KIND_KEYS.modNoCatch)}</span>{/if}
                </li>
            {/each}
        </ul>
    {/if}

    {#if notes.length}
        <p class="modfacts__label">{t(KIND_KEYS.modNotesRaw)}</p>
        <ul class="modfacts__list">
            {#each notes as note}
                <li class="modfacts__item">{note}</li>
            {/each}
        </ul>
    {/if}

    {#if report}
        <p class="modfacts__note">{t(KIND_KEYS.modVersion, { version: report.claude_version })}</p>
    {/if}
    <p class="modfacts__note">{t(KIND_KEYS.modNewSessions)}</p>
    {#if groups.length}
        <p class="modfacts__note">{t(KIND_KEYS.modWhere, { count: groups.length, labels: groups.join(', ') })}</p>
    {/if}

    <label class="modfacts__accept">
        <input type="checkbox" checked={trust} disabled={busy}
            onchange={(event) => onTrust((event.currentTarget as HTMLInputElement).checked)} />
        <span>{t(KIND_KEYS.modTickTrust)}</span>
    </label>
    {#if flaggedNeeded}
        <label class="modfacts__accept">
            <input type="checkbox" checked={flagged} disabled={busy}
                onchange={(event) => onFlagged((event.currentTarget as HTMLInputElement).checked)} />
            <span>{t(KIND_KEYS.modTickFlagged)}</span>
        </label>
    {/if}
</div>

<style>
    .modfacts {
        display: flex;
        flex-direction: column;
        gap: 6px;
        padding: 8px 10px;
        border: 1px solid var(--oc-yellow);
        border-radius: 4px;
    }

    .modfacts__trust {
        margin: 0;
        color: var(--oc-text-primary);
        font-size: 12px;
        line-height: 1.45;
        border-left: 2px solid var(--oc-coral);
        padding-left: 8px;
    }

    .modfacts__label {
        margin: 2px 0 0;
        color: var(--oc-text-secondary);
        font-family: var(--font-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .modfacts__module,
    .modfacts__item {
        margin: 0;
        font-family: var(--font-mono);
        font-size: 11px;
        line-height: 1.5;
        overflow-wrap: anywhere;
    }

    .modfacts__module {
        color: var(--oc-text-muted);
    }

    .modfacts__list {
        margin: 0;
        padding: 0;
        list-style: none;
        max-height: 140px;
        overflow: auto;
    }

    .modfacts__item {
        color: var(--oc-text-primary);
    }

    .modfacts__item--spend,
    .modfacts__spend {
        color: var(--oc-coral);
    }

    .modfacts__note {
        margin: 0;
        color: var(--oc-text-secondary);
        font-size: 11px;
        line-height: 1.4;
    }

    .modfacts__accept {
        display: flex;
        align-items: flex-start;
        gap: 8px;
        color: var(--oc-text-primary);
        font-size: 12px;
        line-height: 1.45;
        cursor: pointer;
    }

    .modfacts__accept input {
        margin-top: 2px;
        flex-shrink: 0;
        width: 16px;
        height: 16px;
    }

    @media (max-width: 767px) {
        .modfacts__accept {
            min-height: 44px;
            align-items: center;
        }

        .modfacts__accept input {
            margin-top: 0;
            width: 22px;
            height: 22px;
        }
    }
</style>
