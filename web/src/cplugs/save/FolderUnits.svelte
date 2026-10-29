
<script lang="ts">
    import { t as reactiveT, type Translate } from '../sdk';
    import { Button, Check } from '../sdk/ui';
    import { megabytes } from './bytes';
    import {
        agoText,
        fetchFolderPoints,
        fetchFolders,
        restoreFolder,
        saveFolderSwitch,
        type Fetcher,
        type FolderPoint,
        type FolderUnit,
    } from './folders-api';
    import { errorText } from './settings-api';

    interface Props {
        t?: Translate;
        fetcher?: Fetcher;
        now?: () => number;
    }
    const { t = reactiveT, fetcher, now = () => Date.now() }: Props = $props();

    let units = $state<readonly FolderUnit[] | null>(null);
    let asking = $state<string | null>(null);
    let points = $state<readonly FolderPoint[]>([]);
    let chosen = $state('');
    let busy = $state(false);
    let note = $state('');
    let problem = $state('');

    async function load(): Promise<void> {
        try {
            units = await fetchFolders(fetcher);
        } catch (error) {
            problem = errorText(error);
            units = [];
        }
    }
    void load();

    function nameOf(unit: FolderUnit): string {
        const named = unit.plugin_name_key ? t(unit.plugin_name_key) : '';
        return t('cplug.save.folders.name', { plugin: named && named !== unit.plugin_name_key ? named : unit.plugin, data: unit.data_id });
    }

    async function flip(unit: FolderUnit, next: boolean): Promise<void> {
        busy = true;
        problem = '';
        note = '';
        try {
            await saveFolderSwitch(unit.unit, next, fetcher);
            await load();
        } catch (error) {
            problem = errorText(error);
        } finally {
            busy = false;
        }
    }

    async function ask(unit: FolderUnit): Promise<void> {
        note = '';
        problem = '';
        asking = unit.unit;
        points = [];
        chosen = '';
        try {
            points = await fetchFolderPoints(unit.unit, fetcher);
            chosen = points[0]?.point_id ?? '';
        } catch (error) {
            problem = errorText(error);
            asking = null;
        }
    }

    async function confirm(unit: FolderUnit): Promise<void> {
        busy = true;
        problem = '';
        try {
            const done = await restoreFolder(unit.unit, chosen, fetcher);
            note = t('cplug.save.folders.restored', { name: nameOf(unit), target: done.target });
            asking = null;
            await load();
        } catch (error) {
            problem = errorText(error);
        } finally {
            busy = false;
        }
    }
</script>

<div class="tm__field" data-tm="folders">
    <span class="oc-key">{t('cplug.save.folders.label')}</span>
    {#if units === null}
        <p class="tm__sub">{t('cplug.save.folders.loading')}</p>
    {:else if units.length === 0}
        <p class="tm__sub" data-tm="folders-empty">{t('cplug.save.folders.empty')}</p>
    {:else}
        <div class="tm__servers">
            {#each units as unit (unit.unit)}
                <div class="tm__srv" data-tm="folder" data-unit={unit.unit}>
                    <div class="tm__srv-head">
                        <span class="tm__srv-name" data-tm="folder-name">{nameOf(unit)}</span>
                        <span class="tm__sub" data-tm="folder-meta">
                            {t('cplug.save.folders.meta', { size: megabytes(unit.bytes), points: unit.points, ago: agoText(unit.last_point_at, now(), t) })}
                        </span>
                        <span class="tm__srv-tools">
                            {#if unit.marked}
                                <Check bare role="switch" label="" ariaLabel={t('cplug.save.folders.backup_switch', { name: nameOf(unit) })}
                                    checked={unit.backup_on} disabled={busy} onToggle={(next) => void flip(unit, next)} data-tm="folder-switch" />
                            {/if}
                            <Button size="sm" data-tm="folder-restore" disabled={busy || unit.points === 0} onclick={() => void ask(unit)}>
                                {t('cplug.save.folders.restore')}
                            </Button>
                        </span>
                    </div>
                    {#if unit.marked && !unit.backup_on}
                        <p class="tm__sub" data-tm="folder-off">{t('cplug.save.folders.backup_off')}</p>
                    {/if}
                    {#if asking === unit.unit}
                        <div class="tm__warn" role="alert" data-tm="folder-confirm">
                            {#if points.length === 0}
                                <p>{t('cplug.save.folders.no_points')}</p>
                            {:else}
                                <p>{t('cplug.save.folders.confirm_text', { name: nameOf(unit), root: unit.root })}</p>
                                <label class="tm__field">
                                    <span class="oc-key">{t('cplug.save.folders.choose')}</span>
                                    <select class="oc-field" bind:value={chosen} disabled={busy} data-tm="folder-point">
                                        {#each points as point (point.point_id)}
                                            <option value={point.point_id}>
                                                {t('cplug.save.folders.point_option', { when: agoText(point.created_at, now(), t), size: megabytes(point.bytes) })}
                                            </option>
                                        {/each}
                                    </select>
                                </label>
                            {/if}
                            <div class="tm__actions">
                                <Button data-tm="folder-cancel" disabled={busy} onclick={() => (asking = null)}>
                                    {t('cplug.save.folders.cancel')}
                                </Button>
                                {#if points.length > 0}
                                    <Button variant="confirm" data-tm="folder-confirm-go" disabled={busy || !chosen} onclick={() => void confirm(unit)}>
                                        {t('cplug.save.folders.confirm')}
                                    </Button>
                                {/if}
                            </div>
                        </div>
                    {/if}
                </div>
            {/each}
        </div>
    {/if}
    {#if note}<p class="tm__note" role="status" data-tm="folders-note">{note}</p>{/if}
    {#if problem}<p class="tm__problem" role="alert" data-tm="folders-problem">{problem}</p>{/if}
</div>
