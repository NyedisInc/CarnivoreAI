
<script lang="ts">
    import { onMount } from 'svelte';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import Page from '../../opscenter/ui/Page.svelte';
    import Button from '../base/Button.svelte';
    import { kindIcon } from '../catalog/card';
    import { MANAGER_KEYS } from '../manager-frame/manager-model';
    import { ledgerRowsOf } from '../skills-page/skill-state';
    import type { createSkillActions } from '../skills-page/skill-actions.svelte';
    import { fetchFeatures } from '../byoai/api';
    import { refusalOf, regenerateCardArt, type Fetcher } from '../skills-page/skills-api';
    import type { ContextChoice, SkillItem } from '../skills-page/skills-model';
    import type { Inventory } from '../skills-page/skills-types';
    import type { Translate } from '../sessions/types';
    import { skillFavorites } from '../themes-page/favorites.svelte';
    import { estimateTokens, triggersOf } from './model';
    import type { SkillMdRead } from './skill-md-api';
    import SkillBrief from './SkillBrief.svelte';
    import SkillDetails from './SkillDetails.svelte';
    import SkillInspector from './SkillInspector.svelte';
    import SkillMdBlock from './SkillMdBlock.svelte';
    import SkillRemoveStrip from './SkillRemoveStrip.svelte';
    import './skill-page.css';

    interface Props {
        item: SkillItem;
        inventory: Inventory | null;
        context: ContextChoice;
        actions: ReturnType<typeof createSkillActions>;
        fetcher: Fetcher;
        t: Translate;
        onOpenCatalog: () => void;
    }

    const { item, inventory, context, actions, fetcher, t, onOpenCatalog }: Props = $props();

    const group = $derived(inventory?.skills.find((g) => g.name === item.id));
    const primary = $derived(group?.locations[0]);
    const firstHarness = $derived(item.harnesses[0]);
    const briefState = $derived(group && firstHarness ? (group.locations.find((l) => l.harness === firstHarness && l.shadowed_by === null) ?? group.locations.find((l) => l.harness === firstHarness))?.state ?? 'off' : 'off');
    const description = $derived(primary?.description ?? '');

    let removing = $state(false);
    let read = $state<SkillMdRead | null>(null);

    const triggers = $derived(read ? triggersOf(read.body, description) : []);
    const inAll = $derived(read ? estimateTokens(item.name, read.body_truncated ? read.size : read.body) : null);
    const starred = $derived(skillFavorites.has(item.id));

    let artRouted = $state<boolean | null>(null);
    let art = $state<{ busy: boolean; message: string | null }>({ busy: false, message: null });

    async function regenerateArt(): Promise<void> {
        const loc = group?.locations.find((l) => l.shadowed_by === null) ?? primary;
        if (!loc || art.busy) return;
        const now = context;
        art = { busy: true, message: null };
        try {
            const queued = await regenerateCardArt(loc.location_id, { projectPath: now.projectPath, profile: now.profile }, fetcher);
            art = { busy: false, message: t(queued ? 'skp.art.queued' : 'skp.art.already') };
        } catch (error) {
            art = { busy: false, message: refusalOf(error, t('skp.art.failed')) };
        }
    }

    onMount(() => {
        void fetchFeatures(fetcher).then(
            (features) => { artRouted = features.some((f) => f.id === 'skills.card_art' && f.target !== null); },
            () => { artRouted = null; },
        );
        return skillFavorites.start();
    });
</script>

{#if group}
    {#snippet pageActions()}
        <Button
            variant="quiet"
            size="sm"
            data-act="favorite"
            aria-pressed={starred}
            aria-label={t('skp.top.favorite', { name: item.name })}
            onclick={() => skillFavorites.toggle(item.id)}
        ><Icon name="star" size={16} strokeWidth={1.4} fill={starred ? 'solid' : 'outline'} /></Button>
        {#if (group?.locations.length ?? 0) > 0}
            <Button
                variant="quiet"
                size="sm"
                data-act="remove-open"
                aria-label={t('skp.top.remove', { name: item.name })}
                aria-expanded={removing}
                aria-controls="skp-rm"
                onclick={() => (removing = !removing)}
            ><Icon name="skull" size={18} strokeWidth={1.6} /></Button>
        {/if}
    {/snippet}
    <div class="skp" data-skill-page={item.id}>
        <Page title={item.name} icon={kindIcon('skill') ?? 'skill'} embedded class="skp-page" actions={pageActions}>
            {#if removing && group.locations.length > 0}
                <SkillRemoveStrip {group} removals={actions.removals} {t} onRemove={(loc) => void actions.remove(loc)} onClose={() => (removing = false)} {onOpenCatalog} />
            {/if}
            <div class="skp-grid">
                <section class="skp-stage" aria-label={t('skp.stage.aria', { name: item.name })}>
                    <div class="skp-cards">
                        <SkillBrief name={item.name} state={briefState} {description} {triggers} tokens={item.tokens} {t} />
                        <SkillDetails
                            name={item.name}
                            {group}
                            ledger={ledgerRowsOf(group, actions.health.ledger)}
                            tripwire={actions.health.tripwire[item.id]}
                            {fetcher}
                            {t}
                            everyTurn={item.tokens}
                            {inAll}
                        />
                    </div>
                    {#if primary}
                        {#key primary.location_id}
                            <SkillMdBlock location={primary} {context} {fetcher} {t} onLoaded={(next) => (read = next)} />
                        {/key}
                    {/if}
                </section>
                <SkillInspector
                    {group}
                    harnesses={item.harnesses}
                    {context}
                    writing={actions.writing}
                    writeError={actions.writeError}
                    {t}
                    art={{ ...art, routed: artRouted }}
                    onRegenerateArt={() => void regenerateArt()}
                    onState={(harness, choice) => void actions.changeState(item, harness, choice)}
                />
            </div>
        </Page>
    </div>
{:else}
    <p class="oc-page__state" role="status">{t(MANAGER_KEYS.loading)}</p>
{/if}
