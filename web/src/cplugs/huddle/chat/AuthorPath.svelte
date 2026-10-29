<script lang="ts">
  import { Glyph, Icon } from '../../sdk/ui';
  import { t } from '../../sdk';
  import { elapsed } from '../huddle-progress';
  import { openAgentPage } from '../agents/agent-page.svelte';
  import type { AuthorCrumb } from './chat-api';
  import { crumbIcon, crumbLabel, crumbLinks } from './author-path';

  let { path, at = null, more = 0, now = Date.now(), lead = false }: { path: AuthorCrumb[]; at?: number | null; more?: number; now?: number; lead?: boolean } = $props();

  const mark = (crumb: AuthorCrumb) => crumbIcon(crumb);
  const since = $derived(typeof at === 'number' && at > 0 ? elapsed(now / 1000 - at) : '');
</script>

<div class="hdc-path" class:hdc-path--lead={lead} data-chat-author-path>
  <nav class="hdc-path-crumbs" aria-label={t('cplug.huddle.chat.head.label')}>
    {#each path as crumb, i (i)}
      {#if i > 0}<span class="hdc-path-sep" aria-hidden="true"><Icon name="chevron-right" size={8} /></span>{/if}
      {#if crumbLinks(crumb)}
        <button type="button" class="hdc-crumb hdc-crumb--link" class:hdc-crumb--lead={lead && i === path.length - 1} data-crumb-kind={crumb.kind} data-crumb-agent={crumb.agent_id} data-agent-drawer-opener
                onclick={() => openAgentPage(crumb.agent_id as number)}>
          {#if lead && i === path.length - 1}{:else if mark(crumb).set === 'glyph'}<Glyph name={mark(crumb).name} size={11} />{:else}<Icon name={mark(crumb).name} size={11} />{/if}<span class="hdc-crumb-name">{crumbLabel(crumb, t('cplug.huddle.chat.you'))}</span>
        </button>
      {:else}
        <span class="hdc-crumb" class:hdc-crumb--lead={lead && i === path.length - 1} data-crumb-kind={crumb.kind}>
          {#if lead && i === path.length - 1}{:else if mark(crumb).set === 'glyph'}<Glyph name={mark(crumb).name} size={11} />{:else}<Icon name={mark(crumb).name} size={11} />{/if}<span class="hdc-crumb-name">{crumbLabel(crumb, t('cplug.huddle.chat.you'))}</span>
        </span>
      {/if}
    {/each}
    {#if more > 0}<span class="hdc-path-more" data-chat-askers-more={more}>{t('cplug.huddle.chat.head.more', { count: more })}</span>{/if}
  </nav>
  {#if since}<time class="hdc-path-time" data-chat-since datetime={new Date((at ?? 0) * 1000).toISOString()}>{since}</time>{/if}
</div>

<style>
  @layer components {
    .hdc-path {
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
      font-family: var(--font-mono);
      font-size: var(--oc-fs-micro);
      color: var(--oc-text-muted);
    }

    .hdc-path-crumbs {
      display: flex;
      flex-wrap: nowrap;
      align-items: center;
      gap: 4px;
      min-width: 0;
      flex: 1 1 auto;
      overflow: hidden;
    }

    .hdc-path-sep {
      display: inline-flex;
      flex: none;
      color: var(--oc-text-muted);
    }

    .hdc-crumb {
      display: inline-flex;
      flex: 0 1 auto;
      align-items: center;
      gap: 4px;
      min-width: 0;
      padding: 0 2px;
      border: 1px solid transparent;
      border-radius: var(--oc-radius-sm, 2px);
      background: none;
      color: var(--oc-text-secondary);
      font: inherit;
      letter-spacing: 0.04em;
    }

    .hdc-crumb-name {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .hdc-crumb--link { cursor: pointer; }

    .hdc-crumb--link:hover { color: var(--oc-text-primary); }

    .hdc-crumb--lead {
      color: var(--oc-text-bright);
      font-size: var(--oc-fs-label);
      font-weight: 700;
      letter-spacing: 0;
    }

    .hdc-path-more {
      flex: none;
      white-space: nowrap;
      color: var(--oc-text-muted);
      letter-spacing: 0.04em;
    }

    .hdc-path-time {
      flex: none;
      margin-left: auto;
      color: var(--oc-text-muted);
      white-space: nowrap;
    }

    .hdc-path--lead .hdc-path-crumbs { flex: 0 1 auto; }
    .hdc-path--lead .hdc-path-time { margin-left: 0; }
  }
</style>
