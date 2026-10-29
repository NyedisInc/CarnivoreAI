
<script lang="ts">
    import type { Snippet } from 'svelte';
    import type { Translate } from '../sessions/types';
    import Tag from '../base/Tag.svelte';
    import InfoTip from '../info-tip/InfoTip.svelte';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import { isLocked } from '../carnivore-account/account-store.svelte';
    import { settingsDoc } from './settings-doc.svelte';
    import { isParentOff } from './setting-parent';
    import { rowDomId, settingKey, type SettingDef } from './settings-registry';

    interface Props {
        def: SettingDef;
        t: Translate;
        inputId?: string | null;
        flash?: boolean;
        solo?: boolean;
        wide?: boolean;
        note?: string | null;
        children: Snippet;
    }

    const { def, t, inputId = null, flash = false, solo = false, wide = false, note = null, children }: Props = $props();

    const status = $derived(settingsDoc.status[def.id] ?? null);
    const waiting = $derived(def.id in settingsDoc.drafts && status?.state !== 'saving');
    const locked = $derived(def.feature !== undefined && isLocked(def.feature));
    const invalid = $derived(settingsDoc.invalidIds.includes(def.id));
    const off = $derived(isParentOff(def));
</script>

<div
    class="sf__row st-row"
    class:st-row--flash={flash}
    class:st-row--dirty={waiting}
    class:st-row--locked={locked}
    class:oc-wide={wide}
    class:st-row--child={def.parent !== undefined}
    class:st-row--off={off}
    class:st-row--lifecycle={def.lifecycle}
    inert={off}
    id={rowDomId(def.id)}
    data-setting-id={def.id}
    data-saves={def.saves}
>
    <div class="st-row__text">
    <div class="st-row__head">
        <span class="st-row__title">
            {#if inputId}
                <label class="sf__label st-row__label" class:st-row__label--solo={solo} for={inputId}>{t(settingKey(def.id, 'label'))}</label>
            {:else}
                <span class="sf__label st-row__label" class:st-row__label--solo={solo}>{t(settingKey(def.id, 'label'))}</span>
            {/if}
            {#if def.info}
                <InfoTip text={t(settingKey(def.id, 'info'))} label={t('settings.info.label')} />
            {/if}
        </span>
        <span class="st-mark" role="status" aria-live="polite">
            {#if status?.state === 'saving'}
                <Tag>{t('settings.status.saving')}</Tag>
            {:else if status?.state === 'saved'}
                <Tag tone="ok">{t('settings.status.saved')}</Tag>
            {:else if status?.state === 'error'}
                <Tag tone="danger">{t('settings.status.error')}</Tag>
            {:else if invalid}
                <Tag tone="danger">{t('settings.status.invalid')}</Tag>
            {:else if waiting}
                <Tag tone="accent">{t('settings.status.unsaved')}</Tag>
            {:else if locked}
                <Tag tone="warn"><span class="st-mark__lock"><span class="st-mark__star" aria-hidden="true"><Icon name="star" size={12} /></span>{t('account.lock.cta')}</span></Tag>
            {/if}
        </span>
    </div>
    <p class="sf__hint st-row__help" class:st-row__label--solo={solo}>{t(settingKey(def.id, 'help'))}</p>
    {#if note}
        <p class="st-row__note">{note}</p>
    {/if}
    </div>
    <div class="sf__control st-row__control">
        {@render children()}
    </div>
    {#if status?.state === 'error'}
        <p class="sf__error" role="alert">{status.message}</p>
    {/if}
</div>
