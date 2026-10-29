
<script lang="ts">
    import Switch from '../../base/Switch.svelte';
    import { MANAGER_KEYS } from '../../manager-frame/manager-model';
    import type { Translate } from '../../sessions/types';
    import { autoSleep, autoSleepActivity, saveAutoSleep, saveUnreadPolicy } from '../../auto-sleep/auto-sleep-store.svelte';
    import { cardSettings, followSettings, setCardSwitch } from '../../crosstalk/terminal-cards/prefs.svelte';
    import { saveAnimations } from '../../motion/animations-pref';
    import { animationsState, refreshAnimations } from '../../motion/animations-state.svelte';
    import { settingsDoc } from '../settings-doc.svelte';
    import { settingKey, type SettingDef } from '../settings-registry';

    interface Props {
        def: SettingDef;
        t: Translate;
    }

    const { def, t }: Props = $props();


    const enabled = $derived.by(() => {
        const c = def.control;
        if (c.kind === 'config-toggle') {
            return !!(settingsDoc.summary?.[c.field.group] as Record<string, unknown> | undefined)?.[c.field.key];
        }
        if (c.kind === 'auto-sleep') return !!autoSleep.data?.enabled;
        if (c.kind === 'auto-sleep-unread') return autoSleep.data?.unread_blocks_sleep ?? false;
        if (c.kind === 'animations') return animationsState.on;
        if (c.kind === 'crosstalk-card') return cardSettings[c.switch];
        return false;
    });
    followSettings();
    const busy = $derived(settingsDoc.status[def.id]?.state === 'saving');
    const ready = $derived(def.control.kind !== 'config-toggle' || settingsDoc.summary !== null);

    function toggle(next: boolean): void {
        const c = def.control;
        if (c.kind === 'config-toggle') {
            void settingsDoc.applyToggle(def.id, c.field, next);
        } else if (c.kind === 'auto-sleep') {
            const minutes = autoSleep.data?.idle_minutes ?? 60;
            void settingsDoc.track(def.id, async () => ((await saveAutoSleep(next, minutes)) ? null : (autoSleepActivity.error ?? t('settings.status.error'))));
        } else if (c.kind === 'auto-sleep-unread') {
            void settingsDoc.track(def.id, async () => ((await saveUnreadPolicy({ unread_blocks_sleep: next })) ? null : (autoSleepActivity.error ?? t('settings.status.error'))));
        } else if (c.kind === 'crosstalk-card') {
            const which = c.switch;
            void settingsDoc.track(def.id, async () => (await setCardSwitch(which, next)));
        } else if (c.kind === 'animations') {
            void settingsDoc.track(def.id, async () => {
                const why = await saveAnimations(next);
                refreshAnimations();
                return why;
            });
        }
    }
</script>

{#if ready}
    <div class="st-switch">
        <Switch
            label=""
            bind:checked={() => enabled, (next) => toggle(next)}
            disabled={busy}
            aria-label={t(MANAGER_KEYS.toggleLabel, { name: t(settingKey(def.id, 'label')) })}
        />
    </div>
{:else}
    <span class="sf__hint">{t('settings.page.loading')}</span>
{/if}

<style>
    .st-switch {
        display: flex;
    }
</style>
