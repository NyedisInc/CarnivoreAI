<script lang="ts">
  /* Escape closes it */
  import './search-d.css';
  import CascadeMenu from '../drawer-tabs/CascadeMenu.svelte';
  import { closing } from '../widget-menu/model';
  import { buttonAttrs } from '../base/classes';
  import Icon from '../../opscenter/ui/Icon.svelte';
  import { t } from '../i18n/index.svelte';
  import type { DeepSearchController } from './deepsearch.svelte';
  import type { DeepGroup, DeepHit } from './deepsearch-api';
  import { hitMenuNodes, runHitAction } from './hit-menu';
  import { hitActions, splitActions, type ActionId, type ConvState } from './result-model';

  interface Props {
    controller: DeepSearchController;
    group: DeepGroup;
    hit: DeepHit;
    conv: ConvState;
    name: string;
  }
  let { controller, group, hit, conv, name }: Props = $props();

  let menuOpen = $state(false);
  let moreButton = $state<HTMLButtonElement | null>(null);

  const ICON: Record<ActionId, string> = { read: 'eye', go: 'terminal', resume: 'play', branch: 'branch', link: 'link', bookmark: 'bookmark', scope: 'search', closest: 'bookmark' };
  const TIPPED: readonly ActionId[] = ['read', 'go', 'resume', 'branch', 'link'];
  const tip = (id: ActionId): string => t(TIPPED.includes(id) ? `deepsearch.action.${id}_tip` : `deepsearch.action.${id}`);
  const ids = $derived(hitActions(conv, group, hit));
  const split = $derived(splitActions(ids));

  const moreNodes = $derived(closing(hitMenuNodes(controller, group, hit, conv, name), () => (menuOpen = false)));

  const run = (id: ActionId): void => runHitAction(controller, group, hit, name, id);
</script>

<div class="sd-acts" role="group" aria-label={t('deepsearch.action.label')} data-testid="deepsearch-actions">
  {#each split.strip as id (id)}
    {#if id === 'read' || id === 'go' || id === 'resume'}
      <button type="button" {...buttonAttrs(id === 'read' ? 'confirm' : 'secondary', 'sm')} data-action={id} title={tip(id)} aria-label={t(`deepsearch.action.${id}`)}
        onmousedown={(e) => e.preventDefault()} onclick={(e) => { e.stopPropagation(); run(id); }}>{t(`deepsearch.action.${id}`)}</button>
    {:else}
      <button type="button" class="sd-ib sd-ib--framed" data-action={id} title={tip(id)} aria-label={t(`deepsearch.action.${id}`)}
        onmousedown={(e) => e.preventDefault()} onclick={(e) => { e.stopPropagation(); run(id); }}><Icon name={ICON[id]} size={12} /></button>
    {/if}
  {/each}
  {#if split.menu.length > 0}
    <button type="button" class="sd-ib sd-ib--framed" data-action="more" aria-haspopup="true" aria-expanded={menuOpen} bind:this={moreButton}
      title={t('deepsearch.action.more')} aria-label={t('deepsearch.action.more')}
      onmousedown={(e) => e.preventDefault()} onclick={(e) => { e.stopPropagation(); menuOpen = !menuOpen; }}><Icon name="kebab" size={12} /></button>
  {/if}
</div>
{#if menuOpen}
  
  <span class="dps__more-host" role="presentation" onclick={(e) => e.stopPropagation()} onkeydown={(e) => e.stopPropagation()}>
    <CascadeMenu root={moreNodes} anchor={moreButton} label={t('deepsearch.action.more')} alignEnd onClose={() => (menuOpen = false)} />
  </span>
{/if}
