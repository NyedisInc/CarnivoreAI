
<script lang="ts">
    import { onMount } from 'svelte';
    import { authFetch } from '../../opscenter/api/auth.svelte';
    import type { Translate } from '../sessions/types';
    import { truncatedTip } from '../tooltip/truncated-tip';
    import type { Fetcher } from '../skills-page/skills-api';
    import { shownEntries, type RequiredEntry } from './required-skills';

    interface Props {
        fetcher?: Fetcher;
        t: Translate;
    }

    const { fetcher = authFetch, t }: Props = $props();

    let entries = $state<RequiredEntry[]>([]);
    async function load(): Promise<void> {
        try {
            const answer = await fetcher<{ items: RequiredEntry[] }>('/catalog/required-skills');
            entries = answer.items;
        } catch {
            entries = [];
        }
    }

    onMount(() => void load());

    const shown = $derived(shownEntries(entries));
</script>

{#if shown.length > 0}
    <div class="sk-required" data-skills-required>
        {#each shown as entry (entry.item_id)}
            <p class="sk-hint sk-required__line" role="status" data-required-state={entry.state}>
                <span class="sk-required__badge">{t('skills.badge.carnivore')}</span>
                {#if entry.state === 'blocked'}
                    <span class="sk-required__text" use:truncatedTip={t('skills.required.blocked', { name: entry.item_id.split('/')[1] ?? entry.item_id })}>{t('skills.required.blocked', { name: entry.item_id.split('/')[1] ?? entry.item_id })}</span>
                {:else if entry.state === 'installed'}
                    <span class="sk-required__text" use:truncatedTip={t('skills.required.local_edits', { name: entry.item_id.split('/')[1] ?? entry.item_id })}>{t('skills.required.local_edits', { name: entry.item_id.split('/')[1] ?? entry.item_id })}</span>
                {/if}
            </p>
        {/each}
    </div>
{/if}

<style>
    @layer components {
        .sk-required__badge {
            color: var(--oc-orange);
            text-transform: uppercase;
            letter-spacing: 0.08em;
            flex: none;
        }

        .sk-required__line {
            display: flex;
            align-items: center;
            gap: var(--oc-space-2);
            min-width: 0;
        }

        .sk-required__text {
            flex: 0 1 auto;
            min-width: 0;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
    }
</style>
