<script lang="ts">
  import { t } from '../sdk';
  import { messageTime, type HuddleItem } from './huddle-model';
  import { trailWho } from './crosstalk-trail';
  import { createTrailFeed } from './crosstalk-trail-feed.svelte';

  let { item }: { item: HuddleItem } = $props();

  const feed = createTrailFeed(() => item.id);
  const rows = $derived(feed.rows);
</script>

{#if rows.length > 0}
  <section class="hdt-trail" data-task-manager-trail={item.id} aria-label={t('cplug.huddle.trail.label')}>
    <h4 class="hdt-trail-label">{t('cplug.huddle.trail.label')}</h4>
    <ol class="hdt-trail-list">
      {#each rows as row (row.id)}
        <li class="hdt-trail-row" data-task-manager-trail-row={row.id}>
          <span class="hdt-trail-who">{trailWho(row, t('cplug.huddle.trail.unknown'))}</span>
          <time class="hdt-trail-time">{messageTime(row.created_at)}</time>
          <span class="hdt-trail-line">{row.preview}</span>
        </li>
      {/each}
    </ol>
  </section>
{/if}

<style>
  @layer components {
    .hdt-trail {
      min-width: 0;
      margin-left: calc(-1 * var(--hdr-lead, 0px));
      border-top: 1px solid var(--oc-line-rule);
      padding-top: 6px;
    }

    .hdt-trail-label {
      margin: 0 0 4px;
      color: var(--oc-text-muted);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-micro);
      font-weight: normal;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .hdt-trail-list {
      list-style: none;
      margin: 0;
      padding: 0;
    }

    .hdt-trail-row {
      display: flex;
      align-items: baseline;
      gap: 8px;
      min-width: 0;
      padding: 2px 0;
      color: var(--oc-text-dim);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-micro);
    }

    .hdt-trail-who {
      flex: none;
      color: var(--oc-text-bright);
    }

    .hdt-trail-time {
      flex: none;
    }

    .hdt-trail-line {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  }
</style>
