
<script lang="ts">
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import '../settings-page/panel-kit/panel-kit.css';
    import { errorText } from '../settings-page/panel-kit/error-text';
    import { enableNativeAlerts, listNativeDevices, removeNativeDevice, type Fetcher, type NativeDeviceRow } from './native-alerts';

    interface Props {
        t?: Translate;
        fetcher?: Fetcher;
    }
    const { t = reactiveT, fetcher }: Props = $props();

    let rows = $state<NativeDeviceRow[] | null>(null);
    let busy = $state(false);
    let note = $state('');
    let problem = $state('');

    async function load(): Promise<void> {
        try {
            rows = await listNativeDevices(fetcher);
        } catch (error) {
            problem = errorText(error);
        }
    }
    void load();

    async function act(work: () => Promise<string>): Promise<void> {
        busy = true;
        note = '';
        problem = '';
        try {
            note = await work();
        } catch (error) {
            problem = error instanceof Error && error.message === 'timeout' ? t('settings.native_alerts.timeout') : errorText(error);
        } finally {
            busy = false;
        }
        await load();
    }

    const turnOn = () =>
        act(async () => {
            await enableNativeAlerts(fetcher);
            return t('settings.native_alerts.on_done');
        });
    const remove = (id: string) =>
        act(async () => {
            await removeNativeDevice(id, fetcher);
            return t('settings.native_alerts.removed');
        });

    function resultText(row: NativeDeviceRow): string {
        return row.last_result
            ? t('settings.native_alerts.last', { status: row.last_result.status, at: row.last_result.at.slice(0, 16).replace('T', ' ') })
            : t('settings.native_alerts.never');
    }
</script>

<div class="tm" data-na="panel">
    <p class="tm__sub">{t('settings.native_alerts.what')}</p>
    <div>
        <button type="button" class="oc-btn oc-btn--confirm" data-na="on" disabled={busy} onclick={() => void turnOn()}>
            {t('settings.native_alerts.on')}
        </button>
    </div>
    {#if rows && rows.length > 0}
        <ul class="tm__figs" data-na="list">
            {#each rows as row (row.id)}
                <li data-na-row={row.id}>
                    {row.platform} {row.environment}: {resultText(row)}
                    <button type="button" class="oc-btn oc-btn--sm" data-na="remove" disabled={busy} onclick={() => void remove(row.id)}>
                        {t('settings.native_alerts.remove')}
                    </button>
                </li>
            {/each}
        </ul>
    {:else if rows}
        <p class="tm__sub" data-na="empty">{t('settings.native_alerts.empty')}</p>
    {/if}
    {#if note}<p class="tm__note" role="status" data-na="note">{note}</p>{/if}
    {#if problem}<p class="tm__problem" role="alert" data-na="problem">{problem}</p>{/if}
</div>
