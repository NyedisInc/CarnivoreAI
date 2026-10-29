
<script lang="ts">
    import { SKILL_KEYS } from '../../../../client/js/labels/skill.js';
    import type { Translate } from '../sessions/types';
    import { offersAutoUpdate } from './installed-actions';
    import type { InstalledItem } from './types';

    interface Props {
        installed: InstalledItem;
        working: boolean;
        busy: boolean;
        t: Translate;
        onToggle: (next: boolean) => void;
    }

    const { installed, working, busy, t, onToggle }: Props = $props();

    const offered = $derived(offersAutoUpdate(installed));
</script>

<div class="auto">
    {#if offered}
        <label class="auto__switch">
            <input
                type="checkbox"
                checked={installed.auto_update === true}
                disabled={busy}
                onchange={(event) => onToggle((event.currentTarget as HTMLInputElement).checked)}
            />
            <span>{working ? t(SKILL_KEYS.updateAutoWorking) : t(SKILL_KEYS.updateAuto)}</span>
        </label>
        <p class="auto__note">{t(SKILL_KEYS.updateAutoDetail)}</p>
    {:else}
        <p class="auto__note">{t(SKILL_KEYS.updateAutoProject)}</p>
    {/if}
</div>

<style>
    .auto {
        display: flex;
        flex-direction: column;
        gap: 4px;
        padding-top: 6px;
        border-top: 1px solid var(--cat-line-quiet);
    }

    .auto__switch {
        display: flex;
        align-items: center;
        gap: 8px;
        color: var(--cat-text);
        font-size: 12px;
        cursor: pointer;
    }

    .auto__switch input {
        width: 16px;
        height: 16px;
        flex-shrink: 0;
    }

    .auto__note {
        margin: 0;
        color: var(--cat-muted);
        font-size: 11px;
        line-height: 1.45;
    }


    @media (max-width: 767px) {
        .auto__switch {
            min-height: 44px;
        }

        .auto__switch input {
            width: 22px;
            height: 22px;
        }
    }
</style>
