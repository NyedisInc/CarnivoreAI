
<script lang="ts" module>
export interface Mark {
    id: PlaceId;
    on: boolean;
    here: boolean;
    word: string;
}
</script>

<script lang="ts">
    import type { Translate } from '../sessions/types';
    import type { WidgetManifest } from '../../opscenter/widgets/types';
    import PlaceAdd from './PlaceAdd.svelte';
    import WidgetTile from './WidgetTile.svelte';
    import WidgetTilePreview from './WidgetTilePreview.svelte';
    import { PLACES, type PlaceId } from './places';
    import { drag, endDrag } from './places-drag.svelte';

    interface Props {
        id: string;
        name: string;
        group: string;
        groupName: string;
        manifest: WidgetManifest;
        brief: string;
        reason: string | null;
        chip: string | null;
        marks: readonly Mark[];
        here: boolean;
        blocked: boolean;
        enabled: boolean;
        selected: boolean;
        unread: boolean;
        live: boolean;
        t: Translate;
        onOpen: () => void;
        onMain: (anchor: HTMLElement) => void;
        onCaret: (anchor: HTMLElement) => void;
    }

    const { id, name, group, groupName, manifest, brief, reason, chip, marks, here, blocked, enabled, selected, unread, live, t, onOpen, onMain, onCaret }: Props = $props();

    function rowClick(event: MouseEvent): void {
        if ((event.target as HTMLElement | null)?.closest('button, a, select, input, label, [role="menu"]')) return;
        onOpen();
    }
</script>

<li
    class="wp-card"
    data-group={group}
    data-dim={reason !== null ? '' : undefined}
    data-off={enabled ? undefined : ''}
    draggable={enabled}
    ondragstart={(event) => {
        drag.widget = id;
        if (event.dataTransfer) {
            event.dataTransfer.effectAllowed = 'copy';
            event.dataTransfer.setData('text/plain', id);
        }
    }}
    ondragend={endDrag}
>
    <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
    <article class="catalog-card" data-group={group} data-item-id={id} data-off={enabled ? undefined : ''} aria-current={selected ? 'true' : undefined} onclick={rowClick}>
        <div class="catalog-card__media">
            <div class="catalog-card__thumb" data-card-media><WidgetTilePreview {manifest} {t} {live} /></div>
        </div>
        <div class="catalog-card__ct">
            <div class="catalog-card__head">
                <span class="catalog-card__name">
                    <WidgetTile {id} icon={manifest.icon} {group} />
                    <span class="wp-card__titles">
                        <button type="button" class="catalog-card__title catalog-card__open" onclick={onOpen}>{name}</button>
                        <span class="catalog-card__group">{groupName}</span>
                    </span>
                </span>
                <span class="catalog-card__slot">
                    {#if chip}
                        <span class="catalog-card__state" class:catalog-card__state--on={enabled}>{chip}</span>
                    {:else}
                        <PlaceAdd {here} {blocked} disabled={unread} {name} {t} onMain={onMain} onCaret={onCaret} />
                    {/if}
                </span>
            </div>
            <p class="catalog-card__brief" class:is-reason={reason !== null}>{reason ?? brief}</p>
            <div class="wp-marks" role="group" aria-label={t('widgets.places.card.marks')}>
                {#each PLACES as def (def.id)}
                    {@const mark = marks.find((one) => one.id === def.id)}
                    <span class="wp-mk" data-pl={def.id} data-on={mark?.on ? '' : undefined} data-here={mark?.here ? '' : undefined} role="img" title={mark?.word} aria-label={unread ? t('widgets.places.card.unknown') : mark?.word}>{def.mark}</span>
                {/each}
            </div>
        </div>
    </article>
</li>
