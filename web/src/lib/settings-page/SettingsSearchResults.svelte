
<script lang="ts">
    import Button from '../base/Button.svelte';
    import Card from '../base/Card.svelte';
    import List from '../base/List.svelte';
    import ListRow from '../base/ListRow.svelte';
    import type { Translate } from '../sessions/types';
    import type { PluginMatch, SettingMatch } from './settings-search';
    import { groupKey, sectionKey, settingKey, type SectionId } from './settings-registry';

    interface Props {
        t: Translate;
        query: string;
        matches: readonly SettingMatch[];
        onJump: (id: string) => void;
        sections?: readonly SectionId[];
        onOpenSection?: (id: SectionId) => void;
        pluginMatches?: readonly PluginMatch[];
        onJumpPlugin?: (match: PluginMatch) => void;
    }

    const { t, query, matches, onJump, sections = [], onOpenSection, pluginMatches = [], onJumpPlugin }: Props = $props();
    const total = $derived(matches.length + sections.length + pluginMatches.length);

    function breadcrumb(match: SettingMatch): string {
        return `${t(sectionKey(match.setting.section, 'label'))} › ${t(groupKey(match.setting.group, 'label'))}`;
    }
</script>

{#snippet hit(attrs: Record<string, string | undefined>, open: () => void, label: string, where: string, help: string)}
    <ListRow wrap>
        {#snippet children()}
            <Button variant="row" {...attrs} onclick={open}>
                <span class="st-hit">
                    <span class="st-hit__top">
                        <span class="st-hit__label">{label}</span>
                        <span class="pl-label st-hit__section">{where}</span>
                    </span>
                    {#if help}<span class="st-hit__help">{help}</span>{/if}
                </span>
            </Button>
        {/snippet}
    </ListRow>
{/snippet}

<section class="st-results" aria-label={t('settings.search.results')}>
    <p class="oc-page__state" role="status">
        {total ? t('settings.search.count', { count: total, query }) : t('settings.search.none', { query })}
    </p>
    {#if total}
        <Card title={t('settings.search.results')}>
            {#snippet children()}
                <List label={t('settings.search.results')}>
                    {#snippet children()}
                        {#each sections as id (id)}
                            {@render hit({ 'data-hit-section': id }, () => onOpenSection?.(id), t(sectionKey(id, 'label')), t('settings.search.section_open'), t(sectionKey(id, 'hint')))}
                        {/each}
                        {#each matches as match (match.setting.id)}
                            {@render hit({ 'data-hit': match.setting.id }, () => onJump(match.setting.id), t(settingKey(match.setting.id, 'label')), breadcrumb(match), t(settingKey(match.setting.id, 'help')))}
                        {/each}
                        {#each pluginMatches as match (`${match.entry.id}:${match.anchor ?? ''}:${match.label}`)}
                            {@render hit(
                                { 'data-hit-plugin': match.entry.id, 'data-hit-anchor': match.anchor ?? undefined },
                                () => onJumpPlugin?.(match),
                                match.label,
                                `${t('settings.plugins.heading')} › ${match.entry.name}`,
                                match.help ?? '',
                            )}
                        {/each}
                    {/snippet}
                </List>
            {/snippet}
        </Card>
    {/if}
</section>

<style>
    .st-results {
        display: flex;
        flex-direction: column;
        gap: 10px;
    }

    .st-hit {
        display: flex;
        flex: 1 1 auto;
        flex-direction: column;
        gap: 4px;
        min-width: 0;
        padding-block: var(--oc-space-2);
    }

    .st-hit__top {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 12px;
    }

    .st-hit__label {
        font-size: 13px;
        color: var(--pl-text);
    }

    .st-hit__help {
        font-size: 11px;
        line-height: 1.45;
        color: var(--pl-muted);
    }
</style>
