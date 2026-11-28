
<script lang="ts">
    import type { Snippet } from 'svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import type { ProfileRow } from '../launch-profiles-page/api';
    import { sessionMark } from '../sessions/agent-marks';
    import Button from '../base/Button.svelte';
    import Field from '../base/Field.svelte';
    import LaunchStory from '../launch-picker/LaunchStory.svelte';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import { brandColorRole, type WizardAccount, type WizardComputer } from './model';

    interface Props {
        profiles: readonly ProfileRow[];
        selectedProfileId: string;
        onSelectProfile: (id: string) => void;
        agentName: string;
        agentNamePlaceholder: string;
        profilesFirst?: boolean;
        betweenFields?: Snippet;
        computers: readonly WizardComputer[];
        selectedComputerKey: string;
        onSelectComputer: (key: string) => void;
        model: string;
        accounts: readonly WizardAccount[];
        selectedAccountId: string | null;
        onSelectAccount: (id: string | null) => void;
        storyRef?: string | null;
        showWorktree?: boolean;
        useWorktree?: boolean;
        onToggleWorktree?: () => void;
        worktreeBranch?: string;
        moreOpen: boolean;
        onToggleMore: () => void;
        t?: Translate;
    }

    let {
        profiles,
        selectedProfileId,
        onSelectProfile,
        agentName = $bindable(''),
        agentNamePlaceholder,
        profilesFirst = false,
        betweenFields,
        computers,
        selectedComputerKey,
        onSelectComputer,
        model = $bindable(''),
        accounts,
        selectedAccountId,
        onSelectAccount,
        storyRef = $bindable<string | null>(null),
        showWorktree = false,
        useWorktree = false,
        onToggleWorktree,
        worktreeBranch = $bindable(''),
        moreOpen,
        onToggleMore,
        t = reactiveT,
    }: Props = $props();

    const selectedProfile = $derived(profiles.find((p) => p.id === selectedProfileId) ?? profiles[0] ?? null);
    const isLocal = $derived(!selectedComputerKey || selectedComputerKey === 'local');
    const matchingAccounts = $derived.by(() => {
        if (!selectedProfile || selectedProfile.account.mode === 'pinned') return [];
        const h = selectedProfile.harness;
        if (h !== 'claude' && h !== 'codex') return [];
        return accounts.filter((a) => a.provider === h);
    });
    const showModelInput = $derived(
        isLocal &&
            selectedProfile !== null &&
            (selectedProfile.model.mode === 'ask' ||
                (selectedProfile.model.mode === 'default' &&
                    (selectedProfile.harness === 'claude' || selectedProfile.harness === 'codex'))),
    );

    const computerLabel = (comp: WizardComputer | undefined): string =>
        !comp || comp.key === 'local' ? t('newagent.computer_local') : comp.label;

    const moreSummary = $derived.by(() => {
        const comp = computers.find((c) => c.key === selectedComputerKey);
        const parts: string[] = [computerLabel(comp)];
        if (model.trim()) parts.push(model.trim());
        else if (selectedProfile?.model.mode === 'fixed' && selectedProfile.model.value) {
            parts.push(selectedProfile.model.value);
        }
        if (showWorktree && useWorktree) parts.push(t('newagent.worktree_on'));
        return parts.join(' / ');
    });
</script>

{#snippet profilePicker()}
    <div class="naw-field-group">
        <span class="naw-label">{t('newagent.launch_profile_label')}</span>
        {#if profiles.length === 0}
            <p class="naw-empty-note">{t('newagent.no_profiles')}</p>
        {:else}
            <div class="naw-profile-grid" role="group" aria-label={t('newagent.launch_profile_label')}>
                {#each profiles as prof (prof.id)}
                    {@const isSelected = prof.id === selectedProfileId}
                    {@const mark = sessionMark(prof.harness, prof.icon, 15)}
                    {@const brand = brandColorRole(prof.harness, prof.icon)}
                    <div class="naw-profile-cell">
                        <Button
                            variant={isSelected ? 'confirm' : 'secondary'}
                            size="auto"
                            aria-pressed={isSelected}
                            data-profile-id={prof.id}
                            onclick={() => onSelectProfile(prof.id)}
                        >
                            <span class="naw-profile-inner">
                                <span class="naw-brand-icon" data-brand={brand || undefined} aria-hidden="true">
                                    {@html mark.svg}
                                </span>
                                <span class="naw-profile-name">{prof.label || prof.id}</span>
                            </span>
                        </Button>
                    </div>
                {/each}
            </div>
        {/if}
    </div>
{/snippet}

{#snippet nameField()}
    <div class="naw-field-group">
        <Field
            label={t('newagent.agent_name_label')}
            placeholder={agentNamePlaceholder}
            bind:value={agentName}
            autocomplete="off"
            block
        />
    </div>
{/snippet}

<div class="naw-fields-stack">
    {#if profilesFirst}
        {@render profilePicker()}
        {@render nameField()}
    {:else}
        {@render nameField()}
        {@render profilePicker()}
    {/if}

    {#if betweenFields}
        {@render betweenFields()}
    {/if}

    {#if isLocal}
        <LaunchStory {t} bind:answer={storyRef} />
    {/if}

    <div class="naw-more-wrap">
        <Button
            variant="quiet"
            size="auto"
            aria-expanded={moreOpen}
            onclick={onToggleMore}
        >
            <span class="naw-more-toggle-inner">
                <span class="naw-more-left">
                    <Icon name={moreOpen ? 'chevron-down' : 'chevron-right'} size={12} />
                    <span>{t('newagent.more_options')}</span>
                </span>
                <span class="naw-more-summary">{moreSummary}</span>
            </span>
        </Button>

        {#if moreOpen}
            <div class="naw-more-panel">
                {#if computers.length > 1}
                    <div class="naw-field-group">
                        <span class="naw-label">{t('newagent.computer_label')}</span>
                        <div class="naw-chip-row" role="group" aria-label={t('newagent.computer_label')}>
                            {#each computers as comp (comp.key)}
                                {@const active = comp.key === selectedComputerKey}
                                <Button
                                    variant={active ? 'confirm' : 'secondary'}
                                    size="sm"
                                    disabled={!comp.online}
                                    aria-pressed={active}
                                    onclick={() => onSelectComputer(comp.key)}
                                >
                                    {comp.online ? computerLabel(comp) : t('newagent.computer_offline', { label: computerLabel(comp) })}
                                </Button>
                            {/each}
                        </div>
                    </div>
                {/if}

                {#if showModelInput}
                    <Field
                        label={t('newagent.model_label')}
                        placeholder={t('newagent.model_placeholder')}
                        bind:value={model}
                        autocomplete="off"
                        block
                    />
                {/if}

                {#if isLocal && matchingAccounts.length > 0}
                    <div class="naw-field-group">
                        <span class="naw-label">{t('newagent.account_label')}</span>
                        <div class="naw-chip-row" role="group" aria-label={t('newagent.account_label')}>
                            <Button
                                variant={selectedAccountId === null ? 'confirm' : 'secondary'}
                                size="sm"
                                aria-pressed={selectedAccountId === null}
                                onclick={() => onSelectAccount(null)}
                            >
                                {t('newagent.account_default')}
                            </Button>
                            {#each matchingAccounts as acct (acct.id)}
                                {@const active = selectedAccountId === acct.id}
                                <Button
                                    variant={active ? 'confirm' : 'secondary'}
                                    size="sm"
                                    aria-pressed={active}
                                    onclick={() => onSelectAccount(acct.id)}
                                >
                                    {acct.name}
                                </Button>
                            {/each}
                        </div>
                    </div>
                {/if}

                {#if isLocal && showWorktree}
                    <div class="naw-field-group">
                        <span class="naw-label">{t('newagent.isolation_label')}</span>
                        <Button
                            variant={useWorktree ? 'confirm' : 'secondary'}
                            size="auto"
                            aria-pressed={useWorktree}
                            onclick={() => onToggleWorktree?.()}
                        >
                            <span class="naw-wt-row">
                                <span>{t('newagent.worktree_toggle')}</span>
                                <span>{useWorktree ? t('newagent.worktree_on') : t('newagent.worktree_off')}</span>
                            </span>
                        </Button>
                        {#if useWorktree}
                            <Field
                                aria-label={t('newagent.worktree_branch_label')}
                                placeholder={t('newagent.worktree_branch_placeholder')}
                                bind:value={worktreeBranch}
                                autocomplete="off"
                                block
                            />
                        {/if}
                    </div>
                {/if}
            </div>
        {/if}
    </div>
</div>

<style>
    @layer components {
        .naw-fields-stack {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-4);
        }

        .naw-field-group {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-1-5);
        }

        .naw-label {
            color: var(--oc-text-muted);
            font-size: var(--oc-fs-micro);
            letter-spacing: var(--oc-tracking-caps);
            text-transform: uppercase;
        }

        .naw-empty-note {
            margin: 0;
            color: var(--oc-text-muted);
            font-size: var(--oc-fs-label);
        }

        .naw-profile-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: var(--oc-space-2);
        }

        .naw-profile-cell {
            min-width: 0;
            display: flex;
            flex-direction: column;
            align-items: stretch;
        }

        .naw-profile-inner {
            display: flex;
            align-items: center;
            justify-content: flex-start;
            gap: var(--oc-space-2);
            min-height: 28px;
            padding: var(--oc-space-1) 0;
            min-width: 0;
            width: 100%;
            text-align: left;
        }

        .naw-brand-icon {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 16px;
            height: 16px;
            flex-shrink: 0;
        }

        .naw-brand-icon[data-brand='green'] {
            color: var(--oc-green);
        }

        .naw-brand-icon[data-brand='violet'] {
            color: var(--oc-violet);
        }

        .naw-brand-icon[data-brand='yellow'] {
            color: var(--oc-yellow);
        }

        .naw-brand-icon[data-brand='cyan'] {
            color: var(--oc-cyan);
        }

        .naw-profile-name {
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            min-width: 0;
            font-size: var(--oc-fs-body);
        }

        .naw-more-wrap {
            border-top: var(--oc-border) solid var(--oc-line-rule);
            padding-top: var(--oc-space-3);
            display: flex;
            flex-direction: column;
            align-items: stretch;
            gap: var(--oc-space-3);
        }

        .naw-more-toggle-inner {
            width: 100%;
            min-height: 26px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: var(--oc-space-2);
        }

        .naw-more-left {
            display: inline-flex;
            align-items: center;
            gap: var(--oc-space-1-5);
            color: var(--oc-text-muted);
            font-size: var(--oc-fs-label);
        }

        .naw-more-summary {
            color: var(--oc-text-dim);
            font-size: var(--oc-fs-micro);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .naw-more-panel {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-3);
            padding: var(--oc-space-3);
            border: var(--oc-border) solid var(--oc-line-panel);
            border-radius: var(--oc-radius-control);
            background: var(--oc-surface-1);
        }

        .naw-chip-row {
            display: flex;
            flex-wrap: wrap;
            gap: var(--oc-space-1-5);
        }

        .naw-wt-row {
            width: 100%;
            min-height: 24px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: var(--oc-space-2);
        }

        @media (max-width: 640px) {
            .naw-profile-grid {
                grid-template-columns: 1fr;
            }
        }
    }
</style>
