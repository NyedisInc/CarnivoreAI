
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import Button from '../base/Button.svelte';
    import SettingsForm from './SettingsForm.svelte';
    import { createItemSettingsController, type ItemSettingsController } from './item-settings-controller.svelte';
    import type { ItemKind } from './api';

    interface Props {
        kind: ItemKind;
        id: string;
        t: Translate;
        controller?: ItemSettingsController;
    }

    const { kind, id, t, controller }: Props = $props();

    // svelte-ignore state_referenced_locally
    const ctl = controller ?? createItemSettingsController(kind, id, t);
    // svelte-ignore state_referenced_locally
    if (ctl.status === 'loading' && !ctl.item) void ctl.load();

    const schema = $derived(ctl.item?.schema ?? null);
    const hasFields = $derived(schema !== null && Object.keys(schema.fields).length > 0);
</script>

{#if ctl.status === 'error'}
    <p class="sf__error" role="alert" data-settings-load-error>{t('item_settings.error.load_named', { reason: ctl.loadError ?? '' })}</p>
    <Button onclick={() => void ctl.load()}>{t('item_settings.retry')}</Button>
{:else if ctl.item && schema && hasFields}
    {#if ctl.notice}<p class="sf__notice" role="status">{ctl.notice}</p>{/if}
    <SettingsForm
        {schema}
        values={ctl.item.values}
        dropped={ctl.item.dropped}
        busyKey={ctl.busyKey}
        error={ctl.fieldError}
        idPrefix={`sf-${kind}-${id.replace(/[^a-z0-9-]/gi, '-')}`}
        {t}
        onChange={(key, value) => void ctl.change(key, value)}
    />
{/if}
