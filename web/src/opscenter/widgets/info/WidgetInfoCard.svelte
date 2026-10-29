<script lang="ts">
  import WidgetIcon from '../../ui/WidgetIcon.svelte';
  import { t } from '../../../lib/i18n/index.svelte';
  import type { Snippet } from 'svelte';
  import type { InfoLine, WidgetInfo } from './widget-info';

  interface MoreFact {
    label: string;
    value: string;
    name: string;
  }

  let {
    info,
    preview,
    more = [],
    hide = [],
  }: {
    info: WidgetInfo;
    preview?: Snippet;
    more?: readonly MoreFact[];
    hide?: readonly string[];
  } = $props();

  function say(line: InfoLine): string {
    return t(line.key, line.params);
  }

  const rows = $derived(
    [
      { label: 'widgets.info.label.group', value: `${t(info.categoryKey)} / ${t(info.typeKey)}`, name: 'group' },
      { label: 'widgets.info.label.copies', value: t(info.instancingKey), name: 'copies' },
      { label: 'widgets.info.label.sizes', value: info.sizes.map(say).join(', '), name: 'sizes' },
      { label: 'widgets.info.label.data', value: say(info.data), name: 'data' },
      ...more,
    ].filter((row) => !hide.includes(row.name)),
  );
</script>

<article class="oc-winfo" data-widget-info={info.id}>
  <header class="oc-winfo-head">
    <span class="oc-winfo-icon" style={`color: var(--${info.iconTone})`}><WidgetIcon name={info.icon} widget={info.id} size={15} /></span>
    <h3 class="oc-winfo-name">{t(info.titleKey)}</h3>
    <span class="oc-winfo-version">{t('widgets.info.version', { version: info.version })}</span>
  </header>
  <p class="oc-winfo-about" data-widget-info-about>{say(info.about)}</p>
  {#if preview}{@render preview()}{/if}
  <dl class="oc-winfo-facts">
    {#each rows as row (row.name)}
      <dt>{t(row.label)}</dt>
      <dd data-widget-info-fact={row.name}>{row.value}</dd>
    {/each}
  </dl>
</article>

<style>
  @layer components {
    .oc-winfo {
      display: flex;
      flex-direction: column;
      gap: var(--oc-space-2);
      min-width: 0;
      font-family: var(--font-mono);
      color: var(--oc-text-primary);
    }

    .oc-winfo-head {
      display: flex;
      align-items: center;
      gap: var(--oc-space-2);
      min-width: 0;
    }

    .oc-winfo-icon {
      display: inline-flex;
      flex: none;
    }

    .oc-winfo-name {
      flex: 1 1 auto;
      min-width: 0;
      margin: 0;
      overflow: hidden;
      font-size: var(--oc-fs-status, 13px);
      font-weight: 400;
      color: var(--oc-text-bright);
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .oc-winfo-version {
      flex: none;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-micro, 10px);
      letter-spacing: var(--oc-tracking-label, 0.6px);
    }

    .oc-winfo-about {
      margin: 0;
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-label, 11px);
      line-height: 1.5;
    }

    .oc-winfo-facts {
      display: grid;
      grid-template-columns: auto minmax(0, 1fr);
      gap: var(--oc-space-1) var(--oc-space-3);
      margin: 0;
      padding-top: var(--oc-space-2);
      box-shadow: inset 0 1px 0 var(--oc-line-rule);
      font-size: var(--oc-fs-label, 11px);
    }

    .oc-winfo-facts dt {
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-micro, 10px);
      letter-spacing: var(--oc-tracking-label, 0.6px);
      text-transform: uppercase;
      line-height: 1.6;
    }

    .oc-winfo-facts dd {
      margin: 0;
      overflow-wrap: anywhere;
    }
  }
</style>
