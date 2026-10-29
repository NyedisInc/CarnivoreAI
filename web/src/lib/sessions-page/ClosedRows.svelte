
<script lang="ts">
    import { providerMark } from '../sessions/agent-marks';
    import FoldChevron from '../../opscenter/ui/FoldChevron.svelte';
    import ListRow from '../base/ListRow.svelte';
    import Button from '../base/Button.svelte';
    import Tag from '../base/Tag.svelte';
    import type { Translate } from '../sessions/types';
    import { diskTag, primaryAction } from '../projects-shared/ledger-model';
    import { previewCount } from './closed-model';
    import type { PageRow } from './filters';
    import { dateWord } from './latest-line';
    import { rowAction, type RowAction } from './row-action';
    import { stateKeyOf } from './row-state';

    interface Props {
        rows: readonly PageRow[];
        selected: string | null;
        busyIds: ReadonlySet<string>;
        searching: boolean;
        t: Translate;
        age: (iso: string | null) => string;
        previousOf: (sessionUuid: string) => number;
        thisComputer: string;
        onSelect: (row: PageRow) => void;
        onAct: (kind: RowAction, row: PageRow) => void;
    }
    const { rows, selected, busyIds, searching, t, age, previousOf, thisComputer, onSelect, onAct }: Props = $props();

    let chosen = $state<boolean | null>(null);
    let all = $state(false);
    const open = $derived(chosen ?? searching);
    const shown = $derived(rows.slice(0, previewCount(rows.length, all)));
</script>

<Button variant="row" data-closed-head aria-expanded={open} onclick={() => (chosen = !open)}>
    <FoldChevron />
    <span class="pl-label">{t('projects.page.group.closed')}</span>
    <span class="sp-sh-m">{rows.length}</span>
</Button>
{#if open}
    {#each shown as r (r.s.session_uuid)}
        {@const s = r.s}
        {@const name = s.label ?? s.title}
        {@const action = rowAction(s)}
        {@const disk = diskTag(s)}
        {@const previous = previousOf(s.session_uuid)}
        {@const why = r.computer === null && !action ? primaryAction(s).disabledReasonKey : undefined}
        {@const mark = providerMark(r.provider)}
        <ListRow class="sp-row sp-row--closed" density="roomy" role="option" data-closed-id={s.session_uuid} data-state={s.state} aria-selected={s.session_uuid === selected} onclick={() => onSelect(r)}>
            <span class="sp-led"></span>
            <div class="sp-l1">
                <span class="sp-c-name">{name}</span>
                <span class="sp-c-state">{t(`sessions.page.state.${stateKeyOf(s, undefined)}`)}</span>
                <span class="sp-c-prov"><span class="sp-mark" role="img" aria-label={mark.label} title={mark.label}>{@html mark.svg}</span><span>{r.provider}</span></span>
                <span class="sp-c-latest">
                    {#if disk === 'on-disk'}<Tag data-tag="on-disk">{t('projects.page.disk.on')}</Tag>{/if}
                    {#if disk === 'gone'}<Tag tone="danger" data-tag="gone">{t('projects.page.disk.gone')}</Tag>{/if}
                    {#if previous > 0}<Tag data-previous-count={previous}>{t('projects.page.pc.row_tag', { count: previous })}</Tag>{/if}
                    {#if s.kind === 'automated'}<Tag>{t('projects.page.tag.automated')}</Tag>{/if}
                </span>
                <span class="sp-c-measure">{age(s.last_activity_at)}</span>
                <span class="sp-c-comp">{r.computer ?? thisComputer}</span>
                <span class="sp-c-start">{dateWord(s.created_at)}</span>
            </div>
            <div class="sp-tail oc-list__actions">
                {#if action}
                    <Button
                        size="sm"
                        data-go={action}
                        disabled={busyIds.has(s.session_uuid)}
                        aria-label={t(`sessions.page.act.${action}.label`, { name })}
                        onclick={(e) => {
                            e.stopPropagation();
                            onAct(action, r);
                        }}
                    >
                        <span>{t(`sessions.page.act.${action}`)}</span>
                    </Button>
                {:else if why}
                    <Button size="sm" data-go="disabled" disabled title={t(why)} aria-label={t(why)}><span>{t('sessions.page.act.resume')}</span></Button>
                {/if}
            </div>
        </ListRow>
    {/each}
    {#if shown.length < rows.length}
        <Button size="sm" data-show-all onclick={() => (all = true)}>{t('projects.page.show_all', { count: rows.length })}</Button>
    {/if}
{/if}
