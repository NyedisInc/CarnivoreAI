<script lang="ts">
  import { Glyph, Icon } from '../../sdk/ui';
  import { t } from '../../sdk';
  import { elapsed } from '../huddle-progress';
  import type { AuthorCrumb } from './chat-api';
  import { crumbIcon, crumbLabel, crumbLinks } from './author-path';
  import { fullPathOf, lineageTip, openAuthorTerminal, pathTip } from './agent-open';

  let { path, at = null, more = 0, now = Date.now(), lead = false }: { path: AuthorCrumb[]; at?: number | null; more?: number; now?: number; lead?: boolean } = $props();

  const own = $derived(path[path.length - 1] ?? null);
  const tip = $derived(own && own.kind !== 'owner' ? pathTip(fullPathOf(path, own.agent_id)) : '');
  const mark = $derived(own ? crumbIcon(own) : null);
  const since = $derived(typeof at === 'number' && at > 0 ? elapsed(now / 1000 - at) : '');
</script>

{#snippet face(crumb: AuthorCrumb)}
  {#if lead}{:else if mark?.set === 'glyph'}<Glyph name={mark.name} size={11} />{:else if mark}<Icon name={mark.name} size={11} />{/if}<span class="hdc-crumb-name">{crumbLabel(crumb, t('cplug.huddle.chat.you'))}</span>
{/snippet}

<div class="hdc-path" class:hdc-path--lead={lead} data-chat-author-path>
  <span class="hdc-path-crumbs">
    {#if own && crumbLinks(own)}
      <button type="button" class="hdc-crumb hdc-crumb--link" class:hdc-crumb--lead={lead} data-crumb-kind={own.kind} data-crumb-agent={own.agent_id}
              use:lineageTip={tip} onclick={() => openAuthorTerminal(own.agent_id, null)}>{@render face(own)}</button>
    {:else if own}
      <span class="hdc-crumb" class:hdc-crumb--lead={lead} data-crumb-kind={own.kind} use:lineageTip={tip}>{@render face(own)}</span>
    {/if}
    {#if more > 0}<span class="hdc-path-more" data-chat-askers-more={more}>{t('cplug.huddle.chat.head.more', { count: more })}</span>{/if}
  </span>
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
