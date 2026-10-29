
<script lang="ts">
    import { MANAGER_KEYS } from '../manager-frame/manager-model';
    import type { Translate } from '../sessions/types';
    import SkillDetail from './SkillDetail.svelte';
    import { ledgerRowsOf } from './skill-state';
    import type { createSkillActions } from './skill-actions.svelte';
    import { fetchLocationSkillMd, type Fetcher } from './skills-api';
    import type { ContextChoice, SkillItem } from './skills-model';
    import type { Inventory } from './skills-types';

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
</script>

{#if group}
    {#key context.id + item.id}
        <SkillDetail
            {item}
            {group}
            {context}
            {t}
            writing={actions.writing}
            writeError={actions.writeError}
            removals={actions.removals}
            onState={(harness, choice) => void actions.changeState(item, harness, choice)}
            onRemove={(location) => void actions.remove(location)}
            {onOpenCatalog}
            {fetcher}
            ledger={ledgerRowsOf(group, actions.health.ledger)}
            tripwire={actions.health.tripwire[item.id]}
            onChanged={() => inventory && void actions.loadHealth(inventory)}
            readMd={(location) => fetchLocationSkillMd(location.location_id, { projectPath: context.projectPath, profile: context.profile }, fetcher)}
        />
    {/key}
{:else}
    <p class="oc-page__state" role="status">{t(MANAGER_KEYS.loading)}</p>
{/if}
