<script lang="ts">
  import { t } from '../../../lib/i18n/index.svelte';
  import Icon from '../../ui/Icon.svelte';
  import { truncatedTip } from '../../../lib/tooltip/truncated-tip';
  import { messageTime, type HuddleItem } from '../../../cplugs/huddle/huddle-model';
  import { trailWho } from '../../../cplugs/huddle/crosstalk-trail';
  import { createTrailFeed } from '../../../cplugs/huddle/crosstalk-trail-feed.svelte';

  let { item }: { item: HuddleItem } = $props();

  const feed = createTrailFeed(() => item.id);
  let opened = $state<Record<string, boolean>>({});
</script>

{#if feed.rows.length > 0}
  <div class="tn-line between"><span class="tn-overline">{t('cplug.huddle.trail.label')}</span><span class="tn-subtle">{feed.rows.length}</span></div>
  <ul class="mk2-xt" data-mk2-crosstalk={item.id} aria-label={t('cplug.huddle.trail.label')}>
    {#each feed.rows as row (row.id)}
      {@const open = opened[row.id] === true}
      <li class="mk2-xt-card" data-mk2-crosstalk-card={row.id} data-open={open ? 'true' : 'false'}>
        <button type="button" class="mk2-xt-head" data-btn="row" aria-expanded={open} aria-label={t(open ? 'cplug.huddle.post.fold' : 'cplug.huddle.post.unfold')}
                onclick={() => { opened[row.id] = !open; }}>
          <span class="mk2-xt-who">{trailWho(row, t('cplug.huddle.trail.unknown'))}</span>
          <time class="mk2-xt-time">{messageTime(row.created_at)}</time>
          <Icon name={open ? 'chevron-up' : 'chevron-down'} size={12} strokeWidth={1.75} />
        </button>
        <p class="mk2-xt-line" class:mk2-xt-line--open={open} use:truncatedTip={row.preview}>{row.preview}</p>
      </li>
    {/each}
  </ul>
{/if}

<style>
  @layer components {
    .mk2-xt {
      display: flex;
      flex-direction: column;
      gap: var(--oc-space-2);
      min-width: 0;
      margin: var(--oc-space-1) 0 0;
      padding: 0;
      list-style: none;
    }

    .mk2-xt-card {
      min-width: 0;
      padding: var(--oc-space-1) var(--oc-space-2);
      background: var(--tm-well);
      border: 1px solid var(--oc-line-panel);
    }

    .mk2-xt-head {
      --_btn-h: 0px;
      --_btn-fill-hover: transparent;
      display: flex;
      align-items: center;
      gap: var(--oc-space-2);
      width: 100%;
      min-width: 0;
      padding: 0;
      color: var(--oc-text-muted);
      cursor: pointer;
      text-align: left;
    }

    .mk2-xt-who {
      flex: 1 1 auto;
      min-width: 0;
      overflow: hidden;
      color: var(--oc-text-primary);
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .mk2-xt-time {
      flex: none;
      font-size: var(--oc-fs-micro);
    }

    .mk2-xt-line {
      margin: 0;
      overflow: hidden;
      color: var(--oc-text-secondary);
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .mk2-xt-line--open {
      overflow-wrap: anywhere;
      white-space: pre-wrap;
    }
  }
</style>
