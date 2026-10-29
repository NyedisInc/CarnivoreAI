
<script lang="ts">
    import Checkbox from '../base/Checkbox.svelte';
    import OrderList from '../../opscenter/ui/OrderList.svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import { FOOT_BAR_ITEM_KINDS, footBarItems, type FootBarItemKind } from './foot-bar-items-store.svelte';
    import { footBarOrder, type FootBarOrderId } from './foot-bar-order-store.svelte';

    interface Props {
        t?: Translate;
    }
    const { t = reactiveT }: Props = $props();

    footBarItems.start();
    footBarOrder.start();

    const label = (kind: FootBarItemKind): string => t(`settings.footbaritems.kind.${kind}`);
    const orderItems = $derived(
        footBarOrder.value.map((id) => ({
            id,
            label: label(id),
            on: footBarItems.effective(id),
            earlier: t('settings.footbarlayout.order.earlier', { item: label(id) }),
            later: t('settings.footbarlayout.order.later', { item: label(id) }),
        })),
    );
</script>

<div class="fbi">
    <div class="fbi__set">
        <span class="oc-sub">{t('settings.footbaritems.show')}</span>
        <div class="oc-grid-4">
            {#each FOOT_BAR_ITEM_KINDS as kind (kind)}
                {@const needsModel = kind === 'effort' && !footBarItems.effective('model')}
                <Checkbox
                    label={label(kind)}
                    bind:checked={() => footBarItems.effective(kind), (next) => footBarItems.set(kind, next)}
                    disabled={needsModel}
                    hint={needsModel ? t('settings.footbaritems.needs_model') : undefined}
                    aria-label={t('settings.footbaritems.toggle', { item: label(kind) })}
                />
            {/each}
        </div>
        <span class="oc-key">{t('settings.footbaritems.always_all')}</span>
    </div>
    <div class="fbi__set">
        <span class="oc-sub">{t('settings.footbarlayout.order.label')}</span>
        <OrderList
            items={orderItems}
            ariaLabel={t('settings.footbarlayout.order.label')}
            onMove={(id, direction) => footBarOrder.move(id as FootBarOrderId, direction)}
        />
    </div>
</div>

<style>
    .fbi {
        display: grid;
        width: 100%;
        min-width: 0;
        grid-template-columns: minmax(0, 1fr);
        gap: var(--oc-space-4);
    }

    .fbi__set {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-2);
        min-width: 0;
    }

    @container oc-main (min-width: 640px) {
        .fbi {
            grid-template-columns: minmax(0, 1fr) 300px;
            gap: var(--oc-space-5);
        }
    }
</style>
