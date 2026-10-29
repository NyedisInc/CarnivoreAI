<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import ConvLed from './ConvLed.svelte';
  import ConvTags from './ConvTags.svelte';
  import HitActions from './HitActions.svelte';
  import { hitMenuNodes } from './hit-menu';
  import { pageRowMenu } from '../item-menu/page-row';
  import HitText from './HitText.svelte';
  import type { DeepSearchController } from './deepsearch.svelte';
  import type { DeepGroup, DeepHit } from './deepsearch-api';
  import { ledKind, stateKey, type ConvState } from './result-model';
  import type { ListingRow } from '../../cplugs/sdk/sessions.svelte';
  import './search-d.css';

  interface Props {
    controller: DeepSearchController;
    group: DeepGroup;
    hit: DeepHit;
    conv: ConvState;
    name: string;
    id: string;
    picked: boolean;
    live?: ListingRow | null;
    meta: string;
    title?: string;
    tags?: boolean;
    onopen: () => void;
  }
  let { controller, group, hit, conv, name, id, picked, live = null, meta, title, tags = true, onopen }: Props = $props();

  function menu() {
    if (!controller.showActions) return null;
    const nodes = hitMenuNodes(controller, group, hit, conv, name);
    return nodes.length ? ({ type: 'pagerow', ctx: { label: t('deepsearch.action.more'), nodes } } as const) : null;
  }
</script>


<div {id} class="sd-hit dps__hit" class:is-focus={picked} role="option" tabindex="-1" aria-selected={picked} {title}
  onmousedown={(e) => e.preventDefault()} onclick={onopen} {...pageRowMenu(menu)} onkeydown={() => undefined}>
  <div class="sd-hit__top"><ConvLed kind={ledKind(conv, group)} live={live ?? undefined} title={t(stateKey(conv))} /><span class="sd-hit__name">{name}</span>{#if tags}<ConvTags {group} {conv} />{/if}<span class="sd-r__meta">{meta}</span></div>
  <div class="sd-hit__snip">{#if hit.fileKind === 'subagent'}<span class="dps__tag">{t('deepsearch.subagent')}</span>{' '}{/if}<HitText snippet={hit.snippet} /></div>
  {#if controller.showActions}<HitActions {controller} {group} {hit} {conv} {name} />{/if}
</div>
