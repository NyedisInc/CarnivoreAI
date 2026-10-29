
<script lang="ts">
    import { onMount } from 'svelte';
    import { t as reactiveT } from '../../i18n/index.svelte';
    import type { Translate } from '../../sessions/types';
    import { authFetch } from '../../../opscenter/api/auth.svelte';
    import { resourcePush } from '../../resource-push/boot';
    import { currentScreenFilter } from '../screen-filter';
    import '../../settings-page/panel-kit/panel-kit.css';
    import Button from '../../base/Button.svelte';
    import List from '../../base/List.svelte';
    import ListRow from '../../base/ListRow.svelte';
    import State from '../../base/State.svelte';
    import { getMutes, setMute, type Fetcher, type MuteScope, type Mutes } from './api';

    interface Props {
        t?: Translate;
        fetcher?: Fetcher;
    }
    const { t = reactiveT, fetcher = authFetch }: Props = $props();

    interface Row { key: string; type: string; scope: MuteScope; device: string | null; where: string }

    let mutes = $state<Mutes | null>(null);
    let labels = $state<Record<string, string>>({});
    let failed = $state(false);
    let busy = $state('');

    async function refresh(): Promise<void> {
        try {
            if (Object.keys(labels).length === 0) {
                const body = await fetcher<{ types?: Array<{ id: string; label_key: string }> }>('/notifications/types');
                labels = Object.fromEntries((body?.types ?? []).map((r) => [r.id, r.label_key]));
            }
            mutes = await getMutes(fetcher);
            failed = false;
        } catch {
            failed = true;
        }
    }

    onMount(() => {
        void refresh();
        return resourcePush().pushOrPoll(() => void refresh(), 15000, ['notification_settings']);
    });

    const rows = $derived.by((): Row[] => {
        if (!mutes) return [];
        const out: Row[] = mutes.everywhere.map((type) => ({
            key: `e:${type}`, type, scope: 'everywhere' as MuteScope, device: null, where: t('settings.notify.mutes.scope.everywhere'),
        }));
        for (const [device, rec] of Object.entries(mutes.devices)) {
            const mine = device === mutes.device;
            const where = mine ? t('settings.notify.mutes.scope.this_device')
                : t('settings.notify.mutes.scope.device', { device: rec.label || device.slice(-4) });
            for (const type of rec.types) out.push({ key: `h:${device}:${type}`, type, scope: 'here', device, where });
        }
        return out;
    });

    function typeName(type: string): string {
        const key = labels[type];
        return key ? t(key) : type;
    }

    async function unmute(row: Row): Promise<void> {
        busy = row.key;
        try {
            const next = await setMute(row.type, row.scope, false, fetcher, row.device);
            if (row.device === null || row.device === mutes?.device) currentScreenFilter()?.applyMutes(next);
            await refresh();
        } catch {
            failed = true;
        } finally {
            busy = '';
        }
    }
</script>

<div class="tm notify-mutes" data-mutes="panel">
    {#if failed}<State kind="error" inline title={t('settings.notify.mutes.failed')} data-mutes="problem" />{/if}
    {#if mutes === null && !failed}
        <State kind="loading" inline title={t('settings.notify.mutes.loading')} data-mutes="loading" />
    {:else if rows.length === 0 && !failed}
        <State inline title={t('settings.notify.mutes.empty')} data-mutes="empty" />
    {:else}
        <List label={t('settings.notify.mutes.col.type')} data-mutes="list">
            {#each rows as row (row.key)}
                <ListRow primary={typeName(row.type)} meta={row.where} data-mute-type={row.type} data-mute-scope={row.scope}>
                    {#snippet actions()}
                        <Button size="sm" disabled={busy === row.key} onclick={() => void unmute(row)}>{t('settings.notify.mutes.unmute')}</Button>
                    {/snippet}
                </ListRow>
            {/each}
        </List>
    {/if}
</div>
