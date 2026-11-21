
<script lang="ts">
    import { Button } from '../../base';
    import Check from '../../../opscenter/ui/Check.svelte';
    import type { Translate } from '../../sessions/types';
    import type { Group } from '../matrix/logic';
    import type { RoutesBody } from './api';
    import { groupState } from './logic';

    interface Props {
        groups: readonly Group[];
        routes: RoutesBody | null;
        selection: { family: string; type: string | null };
        open: Readonly<Record<string, boolean>>;
        count: string;
        onSelect: (family: string, type: string | null) => void;
        onToggleOpen: (family: string) => void;
        onGroup: (family: string, next: boolean) => void;
        onType: (type: string, next: boolean) => void;
        t: Translate;
    }
    const { groups, routes, selection, open, count, onSelect, onToggleOpen, onGroup, onType, t }: Props = $props();

    const ids = (g: Group): string[] => g.rows.map((r) => r.id);
    const onCount = (g: Group): number => ids(g).filter((id) => routes?.types[id]?.on === true).length;
</script>

<section class="ins-panel ins-rail" data-ins="rail">
    <div class="ins-bar"><h2>{t('notify.routing.rail.title')}</h2><span class="ins-count">{count}</span></div>
    {#each groups as g (g.family.id)}
        {@const st = groupState(routes, ids(g))}
        {@const name = t(g.family.label_key)}
        {@const unfolded = open[g.family.id] === true}
        <div class="ins-group">
            <div class="ins-grow" data-group={g.family.id} data-off={st === 'none' ? '' : undefined} data-selected={selection.family === g.family.id && !selection.type ? '' : undefined}>
                <Button variant="quiet" size="bare" data-ins="caret" aria-expanded={unfolded} aria-label={t(unfolded ? 'notify.routing.group.fold' : 'notify.routing.group.unfold', { group: name })} onclick={() => onToggleOpen(g.family.id)}>{unfolded ? '−' : '+'}</Button>
                <Button variant="quiet" size="bare" data-ins="gname" aria-pressed={selection.family === g.family.id && !selection.type} data-select={g.family.id} onclick={() => onSelect(g.family.id, null)}>{name}</Button>
                <Check bare role="switch" label="" ariaLabel={t('notify.routing.group.toggle', { group: name })} checked={st === 'all'} mixed={st === 'some'} data-ins="group-switch" data-group-switch={g.family.id}
                    onToggle={() => onGroup(g.family.id, st !== 'all')} />
                <span class="ins-gsum">{t(st === 'some' ? 'notify.routing.group.sum.some' : 'notify.routing.group.sum', { on: onCount(g), total: g.rows.length })}</span>
            </div>
            {#if unfolded}
                {#each g.rows as r (r.id)}
                    {@const on = routes?.types[r.id]?.on === true}
                    <div class="ins-trow" data-type={r.id} data-off={on ? undefined : ''} data-selected={selection.type === r.id ? '' : undefined}>
                        <Button variant="quiet" size="bare" data-ins="tname" aria-pressed={selection.type === r.id} data-select-type={r.id} onclick={() => onSelect(g.family.id, r.id)}>{t(r.label_key)}</Button>
                        <Check bare role="switch" label="" ariaLabel={t(r.label_key)} checked={on} data-ins="type-switch" data-type-switch={r.id} onToggle={(next) => onType(r.id, next)} />
                    </div>
                {/each}
            {/if}
        </div>
    {/each}
</section>
