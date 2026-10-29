
<script lang="ts">
    import { SKILL_KEYS } from '../../../../client/js/labels/skill.js';
    import type { Translate } from '../sessions/types';
    import type { NameTakenChoice } from './types';

    interface Props {
        choices: NameTakenChoice[];
        name: string;
        selected: string | null;
        onChoose: (choice: string | null) => void;
        t: Translate;
    }

    const { choices, name, selected, onChoose, t }: Props = $props();
</script>

<div class="sheet__choices">
    <p class="sheet__choices-heading">{t(SKILL_KEYS.sheetNameTakenHeading, { name })}</p>
    {#each choices as option}
        <label class="sheet__radio">
            <input
                type="radio"
                name="catalog-choice"
                value={option.choice ?? ''}
                checked={selected === option.choice}
                onchange={() => onChoose(option.choice ?? null)}
            />
            <span class="sheet__radio-label">
                {option.choice === 'replace'
                    ? t(SKILL_KEYS.sheetChoiceReplace)
                    : t(SKILL_KEYS.sheetChoiceRename, { name: option.name || '' })}
            </span>
            <span class="sheet__radio-detail">
                {t(SKILL_KEYS.sheetChoiceCounts, {
                    added: option.added ?? 0,
                    changed: option.changed ?? 0,
                    removed: option.removed ?? 0,
                })}
                {#if option.bytes_delta !== null && option.bytes_delta !== undefined}
                    {' '}{t(SKILL_KEYS.sheetChoiceDelta, { bytes: option.bytes_delta })}
                {/if}
            </span>
        </label>
    {/each}
</div>

<style>
    .sheet__choices {
        display: flex;
        flex-direction: column;
        gap: 6px;
        padding: 8px 10px;
        border: 1px solid var(--oc-yellow);
        border-radius: 4px;
    }

    .sheet__choices-heading {
        margin: 0;
        color: var(--oc-text-primary);
        font-size: 12px;
    }

    .sheet__radio {
        display: grid;
        grid-template-columns: auto 1fr;
        align-items: baseline;
        gap: 2px 8px;
        cursor: pointer;
        font-size: 12px;
    }

    .sheet__radio-label {
        color: var(--oc-text-primary);
    }

    .sheet__radio-detail {
        grid-column: 2;
        color: var(--oc-text-secondary);
        font-size: 11px;
    }

    @media (max-width: 767px) {
        .sheet__radio {
            align-items: center;
            min-height: 44px;
        }
    }
</style>
