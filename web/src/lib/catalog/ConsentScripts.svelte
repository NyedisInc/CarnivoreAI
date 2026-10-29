<!-- anything at all -->
<script lang="ts">
    import { SKILL_KEYS } from '../../../../client/js/labels/skill.js';
    import type { Translate } from '../sessions/types';
    import { MAX_SCRIPT_FILES, boundedList, boundedPath } from './bounds';
    import type { PreviewFile } from './types';

    interface Props {
        scripts: readonly PreviewFile[];
        accepted: boolean;
        expressible: boolean;
        busy: boolean;
        t: Translate;
        onAccept: (next: boolean) => void;
    }

    const { scripts, accepted, expressible, busy, t, onAccept }: Props = $props();

    const listed = $derived(boundedList(scripts, MAX_SCRIPT_FILES));
</script>

<div class="consent">
    <p class="consent__heading">{t(SKILL_KEYS.consentScriptsHeading)}</p>
    <ul class="consent__files">
        {#each listed.shown as file}
            <li class="consent__file">{boundedPath(file)}</li>
        {/each}
    </ul>
    {#if listed.hidden > 0}
        
        <p class="consent__more" role="status">
            {t(SKILL_KEYS.filesMore, { count: listed.hidden })}
        </p>
    {/if}
    <p class="consent__warning">{t(SKILL_KEYS.consentScriptsRun)}</p>
    <label class="consent__accept">
        <input
            type="checkbox"
            checked={accepted}
            disabled={busy || !expressible}
            onchange={(event) => onAccept((event.currentTarget as HTMLInputElement).checked)}
        />
        <span>{t(SKILL_KEYS.consentCheckbox)}</span>
    </label>
    {#if !expressible}
        
        <p class="consent__note" role="status">{t(SKILL_KEYS.refusedUnsupported)}</p>
    {/if}
</div>

<style>
    .consent {
        display: flex;
        flex-direction: column;
        gap: 6px;
        padding: 8px 10px;
        border: 1px solid var(--oc-yellow);
        border-radius: 4px;
    }

    .consent__heading {
        margin: 0;
        color: var(--oc-text-secondary);
        font-family: var(--font-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .consent__files {
        max-height: 120px;
        overflow: auto;
        margin: 0;
        padding: 0;
        list-style: none;
    }

    .consent__file {
        color: var(--oc-yellow);
        font-family: var(--font-mono);
        font-size: 11px;
        line-height: 1.5;
        overflow-wrap: anywhere;
    }

    .consent__warning {
        margin: 0;
        color: var(--oc-text-primary);
        font-size: 12px;
        line-height: 1.45;
    }

    .consent__note,
    .consent__more {
        margin: 0;
        color: var(--oc-text-secondary);
        font-size: 11px;
        line-height: 1.4;
    }

    .consent__accept {
        display: flex;
        align-items: flex-start;
        gap: 8px;
        color: var(--oc-text-primary);
        font-size: 12px;
        line-height: 1.45;
        cursor: pointer;
    }

    .consent__accept input {
        margin-top: 2px;
        flex-shrink: 0;
        width: 16px;
        height: 16px;
    }


    @media (max-width: 767px) {
        .consent__accept {
            min-height: 44px;
            align-items: center;
        }

        .consent__accept input {
            margin-top: 0;
            width: 22px;
            height: 22px;
        }
    }
</style>
