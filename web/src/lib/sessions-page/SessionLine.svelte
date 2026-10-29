
<script lang="ts">
    import Icon from '../../opscenter/ui/Icon.svelte';
    import Button from '../base/Button.svelte';
    import ListRow from '../base/ListRow.svelte';
    import { providerMark } from '../sessions/agent-marks';
    import type { SessionListItem, Translate } from '../sessions/types';
    import { projectColorOf } from '../project-colors/store.svelte';
    import { projectColorVar } from '../project-colors/palette';
    import type { PageRow } from './filters';
    import { pageRowMenu } from '../item-menu/page-row';
    import { sessionMenuContext } from '../projects-shared/session-menu-context';
    import RowLed from './RowLed.svelte';
    import { dateWord, latestView } from './latest-line';
    import type { LatestLine } from './sessions-data.svelte';
    import type { LensKey } from './lenses';
    import { stateKeyOf } from './row-state';
    import { rowAction, type RowAction } from './row-action';

    interface Props {
        row: PageRow;
        live: SessionListItem | undefined;
        latest: LatestLine | undefined;
        measure: string;
        asleepUnread: boolean;
        selected: boolean;
        lens: LensKey;
        now: number;
        thisComputer: string;
        t: Translate;
        onSelect: (row: PageRow) => void;
        onAct: (kind: RowAction, row: PageRow) => void;
    }
    const { row, live, latest, measure, asleepUnread, selected, lens, now, thisComputer, t, onSelect, onAct }: Props = $props();

    const s = $derived(row.s);
    const name = $derived(s.label ?? s.title);
    const mark = $derived(providerMark(row.provider));
    const view = $derived(latestView(s, latest, now, t));
    const stateKey = $derived(stateKeyOf(s, live));
    const action = $derived(rowAction(s));
    const created = $derived(dateWord(s.created_at));

    function menu() {
        const ctx = sessionMenuContext(s, live, asleepUnread);
        return ctx ? ({ type: 'session', ctx } as const) : null;
    }
</script>

<ListRow
    class="sp-row"
    density="roomy"
    role="option"
    id="sp-rw-{s.session_uuid}"
    data-id={s.session_uuid}
    aria-selected={selected}
    tabindex={-1}
    onclick={() => onSelect(row)}
    {...pageRowMenu(menu)}
>
    <span class="sp-led">
        <RowLed {row} {live} {asleepUnread} />
    </span>
    <div class="sp-l1">
        <span class="sp-c-name">{name}</span>
        <span class="sp-c-state">{t(`sessions.page.state.${stateKey}`)}</span>
        <span class="sp-c-proj">
            <span class="sp-pchip" style:--pc={projectColorVar(projectColorOf(row.projectRef?.id ?? null))}>{(row.project.charAt(0) || '?').toUpperCase()}</span>
            <span>{row.project}</span>
        </span>
        <span class="sp-c-prov"><span class="sp-mark" role="img" aria-label={mark.label} title={mark.label}>{@html mark.svg}</span><span>{row.provider}</span></span>
        <span class="sp-c-latest" title={view.text}>
            {#if view.stamp}<span class="sp-dt">{view.stamp}</span>{/if}
            <span class="sp-tx" class:sp-dim={view.kind === 'none'}>{view.text}</span>
        </span>
        <span class="sp-c-measure" data-lens-measure={lens}>{measure}</span>
        <span class="sp-c-comp">{row.computer ?? thisComputer}</span>
        <span class="sp-c-start">{created}</span>
    </div>
    <div class="sp-tail oc-list__actions">
    {#if action}
        <Button
            size="sm"
            data-go={action}
            aria-label={t(`sessions.page.act.${action}.label`, { name })}
            onclick={(e) => {
                e.stopPropagation();
                onAct(action, row);
            }}
        >
            {#if action === 'open'}<Icon name="prompt-open" size={14} />{:else if action === 'wake'}<Icon name="bolt" size={14} />{/if}
            <span>{t(`sessions.page.act.${action}`)}</span>
        </Button>
    {/if}
    </div>
</ListRow>
