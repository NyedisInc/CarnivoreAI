
<script lang="ts">
    import { KIND_KEYS, kindLabel } from '../../../../client/js/labels/catalog-kind.js';
    import { SKILL_KEYS } from '../../../../client/js/labels/skill.js';
    import type { Translate } from '../sessions/types';
    import { MAX_PREVIEW_FILES, boundedList } from './bounds';
    import type { LoadoutFacts } from './loadout-facts';

    interface Props {
        facts: LoadoutFacts;
        t: Translate;
    }

    const { facts, t }: Props = $props();

    const listed = $derived(boundedList(facts.members, MAX_PREVIEW_FILES));
</script>

<p class="members__heading">{t(KIND_KEYS.loadoutMembersHeading)}</p>

{#if listed.shown.length}
    <ul class="members">
        {#each listed.shown as member}
            <li class="members__item">
                <span class="members__name">
                    {t(KIND_KEYS.loadoutMemberLine, {
                        title: member.title,
                        version: member.version ?? '',
                    })}
                </span>
                {#if member.kind}
                    
                    {#if kindLabel(member.kind, t)}
                        <span class="members__kind">{kindLabel(member.kind, t)}</span>
                    {/if}
                {/if}
                {#if member.installed}
                    <span class="members__state">{t(KIND_KEYS.loadoutMemberInstalled)}</span>
                {/if}
                {#if member.needsScripts}
                    <span class="members__scripts">{t(KIND_KEYS.loadoutMemberScripts)}</span>
                {/if}
                {#if member.writesInstructions}
                    
                    <span class="members__scripts" data-instructions-write-mark>{t(KIND_KEYS.loadoutMemberInstructions)}</span>
                {/if}
            </li>
        {/each}
    </ul>
    {#if listed.hidden > 0}
        
        <p class="members__more" role="status">
            {t(SKILL_KEYS.filesMore, { count: listed.hidden })}
        </p>
    {/if}
{:else}
    <p class="members__absent" role="status">{t(KIND_KEYS.loadoutMembersAbsent)}</p>
{/if}

{#if facts.anyTheme}
    <p class="members__note" role="note">{t(KIND_KEYS.loadoutThemeNote)}</p>
{/if}

<style>
    .members__heading {
        margin: 6px 0 0;
        color: var(--oc-text-secondary);
        font-size: 11px;
        text-transform: lowercase;
    }

    .members {
        display: flex;
        flex-direction: column;
        gap: 4px;
        margin: 4px 0 0;
        padding: 0;
        list-style: none;
    }

    .members__item {
        display: flex;
        flex-wrap: wrap;
        align-items: baseline;
        gap: 6px;
        font-size: 12px;
        color: var(--oc-text-primary);
    }

    .members__kind,
    .members__state {
        padding: 2px 5px;
        border: 1px solid var(--oc-line-rule);
        border-radius: 3px;
        color: var(--oc-text-muted);
        font-size: 10px;
    }

    .members__scripts {
        padding: 2px 5px;
        border: 1px solid var(--oc-yellow, var(--oc-line-rule));
        border-radius: 3px;
        color: var(--oc-yellow, var(--oc-text-primary));
        font-size: 10px;
    }

    .members__more,
    .members__absent,
    .members__note {
        margin: 4px 0 0;
        color: var(--oc-text-secondary);
        font-size: 11px;
    }
</style>
