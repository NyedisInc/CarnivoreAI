<script lang="ts">
  import { sessionRowForConversation } from '../../cplugs/sdk/sessions.svelte';
  import { t } from '../i18n/index.svelte';
  import './search-d.css';
  import HitRow from './HitRow.svelte';
  import PromptRow from './PromptRow.svelte';
  import MoreInConversation from './MoreInConversation.svelte';
  import type { DeepSearchController } from './deepsearch.svelte';
  import type { DeepGroup } from './deepsearch-api';
  import { HIT_ID_PREFIX, RESULTS_ID } from './ids';
  import { conversationName, conversationState, hitClock, relativeWhen, startIndexes, stateKey, visibleHits, type ConvState, type Layout } from './result-model';

  interface Props {
    controller: DeepSearchController;
    layout: Layout;
  }
  let { controller, layout }: Props = $props();
  const starts = $derived(startIndexes(controller.groups, controller.expanded));
  const now = new Date();

  function whereText(group: DeepGroup, conv: ConvState): string {
    const parts = [group.project, t(stateKey(conv))];
    if (layout === 'ledger') parts.push(t(group.matches === 1 ? 'deepsearch.hits_one' : 'deepsearch.hits_many', { count: group.matches }));
    return parts.filter(Boolean).join(' · ');
  }

  function noteText(conversationId: string, remote: boolean, computer: string): string {
    if (controller.notes[conversationId] !== 'none') return t('deepsearch.open_failed');
    return remote ? t('deepsearch.on_computer', { computer }) : t('deepsearch.no_session');
  }
</script>

<div id={RESULTS_ID} role="listbox" aria-label={t('deepsearch.results_label')} class="sd-scope sd-list dps__list" data-layout={layout}>
    {#each controller.groups as group (group.conversationId)}
      {@const live = sessionRowForConversation(group.conversationId)}
      {@const conv = conversationState(group, live)}
      {@const name = conversationName(group, live?.label, t)}
      {@const open = controller.expanded[group.conversationId] === true}
      {#if controller.notes[group.conversationId]}
        <p class="dps__note">{noteText(group.conversationId, conv === 'computer', group.hostLabel ?? group.hostKey ?? '')}</p>
      {/if}
      {#each visibleHits(group, open) as hit, hi (hi)}
        {@const index = (starts[group.conversationId] ?? 0) + hi}
        {@const who = t(`deepsearch.kind.${hit.kind}`)}
        {#if controller.promptStyle}
          <PromptRow {hit} {name} when={relativeWhen(hit.at ?? group.lastActive, now, t)} id={`${HIT_ID_PREFIX}${index}`}
            picked={index === controller.active} onopen={() => void controller.clickHit(index, group, hit, name)} />
        {:else}
        <HitRow {controller} {group} {hit} {conv} {name} {live} title={whereText(group, conv)} tags={hi === 0} id={`${HIT_ID_PREFIX}${index}`} picked={index === controller.active}
          meta={layout === 'ledger' ? `${who} ${hitClock(hit.at, now)}` : `${who}, ${relativeWhen(hit.at ?? group.lastActive, now, t)}`}
          onopen={() => void controller.clickHit(index, group, hit, name)} />
        {/if}
      {/each}
      <MoreInConversation {controller} {group} />
    {/each}
</div>
