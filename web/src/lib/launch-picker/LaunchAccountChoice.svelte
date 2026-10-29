
<script lang="ts" module>
    let nextId = 0;
</script>

<script lang="ts">
    import { Button } from '../base';
    import Check from '../../opscenter/ui/Check.svelte';
    import ChoiceDropdown from '../dropdown/ChoiceDropdown.svelte';
    import { t as appT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import type { RestartAccounts } from './account-types';
    import { summaryOf, tagKeys } from './account-model';

    interface Props {
        answer: RestartAccounts;
        expanded?: boolean;
        accountId?: string;
        pinned?: boolean;
        followWords: string;
        t?: Translate;
    }
    let { answer, expanded = $bindable(false), accountId = $bindable(''), pinned = $bindable(false), followWords, t = appT }: Props = $props();

    const items = $derived(answer.options.map((o) => ({ id: o.id, label: o.name, o })));
    const summaryOption = $derived(summaryOf(answer));
    const uid = `lac-${(nextId += 1)}`;
    const panelId = `${uid}-panel`;
</script>

<div class="lac" data-launch-account>
    {#if !expanded}
        <span class="lac-summary" data-lac-summary>
            {t('launch_picker.account.summary', { name: summaryOption?.name ?? followWords })}
            {#if summaryOption}{#each tagKeys(summaryOption, answer) as key (key)}<span class="lac-tag">{t(key)}</span>{/each}{/if}
        </span>
    {/if}
    <Button variant="quiet" size="sm" aria-expanded={expanded} aria-controls={expanded ? panelId : undefined} data-lac-link onclick={() => (expanded = !expanded)}>
        {expanded ? t('launch_picker.account.collapse') : t('launch_picker.account.expand')}
    </Button>
    {#if expanded}
        <div class="lac-panel" id={panelId}>
            <span class="lac-label">{t('launch_picker.account.label')}</span>
            <ChoiceDropdown {items} value={accountId} label={t('launch_picker.account.label')} dataKey="launch-account" {t} onChange={(id) => (accountId = id)}>
                {#snippet row(item)}
                    <span class="lac-row">
                        <span class="lac-name">{item.label}</span>
                        {#each tagKeys(item.o, answer) as key (key)}<span class="lac-tag">{t(key)}</span>{/each}
                    </span>
                {/snippet}
            </ChoiceDropdown>
            <Check id={`${uid}-pin`} data-lac-pin="" label={t('launch_picker.account.pin')} checked={pinned} onToggle={(next) => (pinned = next)} />
        </div>
    {/if}
</div>

<style>
    @layer components {
        .lac { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 10px; min-width: 0; font-family: var(--font-mono); }

        .lac-summary { display: inline-flex; flex-wrap: wrap; align-items: center; gap: 4px 6px; min-width: 0; color: var(--oc-text-secondary); font-size: 12px; overflow-wrap: anywhere; }

        .lac-panel { display: flex; flex: 1 1 100%; flex-direction: column; gap: 6px; min-width: 0; }

        .lac-label { color: var(--oc-text-muted); font-size: 10px; letter-spacing: var(--oc-tracking-label, 0.6px); text-transform: uppercase; }

        .lac-row { display: flex; flex-wrap: wrap; align-items: center; gap: 2px 6px; min-width: 0; font-size: 12px; color: var(--oc-text-primary); }

        .lac-name { min-width: 0; overflow-wrap: anywhere; }

        .lac-tag { flex: none; padding: 0 5px; border: 1px solid var(--oc-line-rule); border-radius: 2px; color: var(--oc-text-muted); font-size: 10px; letter-spacing: var(--oc-tracking-label, 0.6px); text-transform: uppercase; white-space: nowrap; }

        @media (max-width: 767px) {
            .lac :global([data-lac-link]) { min-height: 44px; flex: 1 1 100%; justify-content: flex-start; }
            .lac-panel :global([data-lac-pin]) { width: 100%; min-height: 44px; white-space: normal; overflow: visible; }
            .lac-panel :global([data-lac-pin] span) { white-space: normal; overflow-wrap: anywhere; }
        }
    }
</style>
