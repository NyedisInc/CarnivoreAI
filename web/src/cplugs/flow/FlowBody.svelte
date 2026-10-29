<script lang="ts">
  import { tick, untrack } from 'svelte';
  import { t } from '../sdk';
  import { Button, Check } from '../sdk/ui';
  import { FlowFeed } from './flow-feed.svelte';
  import { seedFromSearch, type FlowSeed } from './flow-model';
  import FlowBubble from './FlowBubble.svelte';
  import FlowCard from './FlowCard.svelte';
  import './flow.css';

  const SEED_KEY = 'carnivore.flow.seed';
  const NEAR_BOTTOM = 48;

  const feed = new FlowFeed();
  let kind = $state<FlowSeed['kind']>('huddle_item');
  let ref = $state('');
  let follow = $state(true);
  let stream = $state<HTMLOListElement | null>(null);

  function remembered(): FlowSeed | null {
    try {
      const raw = JSON.parse(localStorage.getItem(SEED_KEY) ?? 'null') as Partial<FlowSeed> | null;
      return raw && (raw.kind === 'huddle_item' || raw.kind === 'session') && typeof raw.id === 'string' ? { kind: raw.kind, id: raw.id } : null;
    } catch {
      return null;
    }
  }

  function openSeed(event?: SubmitEvent): void {
    event?.preventDefault();
    const id = ref.trim().replace(/^#/, '');
    if (!id) return;
    const seed: FlowSeed = { kind, id };
    try {
      localStorage.setItem(SEED_KEY, JSON.stringify(seed));
    } catch {
    }
    follow = true;
    feed.open(seed);
  }

  function onScroll(): void {
    if (!stream) return;
    const atBottom = stream.scrollHeight - stream.scrollTop - stream.clientHeight <= NEAR_BOTTOM;
    if (!atBottom && follow) follow = false;
  }

  $effect(() => {
    untrack(() => {
      feed.start();
      const seed = seedFromSearch(window.location.search) ?? remembered();
      if (seed) {
        kind = seed.kind;
        ref = seed.id;
        feed.open(seed);
      }
    });
    return () => feed.stop();
  });

  $effect(() => {
    void feed.appended;
    if (!follow || !stream) return;
    void tick().then(() => {
      if (stream) stream.scrollTop = stream.scrollHeight;
    });
  });
</script>

<div class="flw" data-flow-body>
  <form class="flw-bar" onsubmit={openSeed}>
    <span class="flw-label">{t('cplug.flow.chat.seed')}</span>
    <select data-field data-size="sm" bind:value={kind} aria-label={t('cplug.flow.chat.seed_kind')}>
      <option value="huddle_item">{t('cplug.flow.chat.seed.huddle_item')}</option>
      <option value="session">{t('cplug.flow.chat.seed.session')}</option>
    </select>
    <input data-field data-size="sm" class="flw-id" data-flow-seed-id bind:value={ref} aria-label={t('cplug.flow.chat.seed_id')}
           placeholder={t(kind === 'session' ? 'cplug.flow.chat.seed.session_hint' : 'cplug.flow.chat.seed.item_hint')} />
    <Button type="submit" size="sm">{t('cplug.flow.chat.open')}</Button>
    <span class="flw-follow"><Check label={t('cplug.flow.chat.follow')} checked={follow} role="switch" onToggle={(next) => (follow = next)} /></span>
  </form>

  {#if feed.seed}
    <div class="flw-head">
      <span class="flw-title">{feed.title || feed.seed.id}</span>
      <span>{t('cplug.flow.chat.count', { count: feed.items.length })}</span>
      {#each feed.warnings.slice(0, 2) as warning (warning)}<span class="flw-meta--warn">{warning}</span>{/each}
    </div>
  {/if}

  {#if feed.error}
    <p class="flw-note flw-note--error" role="status">{t(feed.error)}</p>
  {:else if !feed.seed}
    <p class="flw-note">{t('cplug.flow.chat.empty')}</p>
  {:else if feed.loading && feed.items.length === 0}
    <p class="flw-note" role="status">{t('cplug.flow.chat.loading')}</p>
  {:else if feed.items.length === 0}
    <p class="flw-note">{t('cplug.flow.chat.nothing')}</p>
  {/if}

  <ol class="flw-stream" bind:this={stream} onscroll={onScroll} aria-live="polite" aria-label={t('cplug.flow.chat.title')}>
    {#each feed.items as item (item.id)}
      {@const lane = feed.lanes.get(item.lane)}
      <li class="flw-entry" class:flw-entry--owner={item.kind === 'bubble' && item.role === 'prompt'} style:--_depth={lane?.depth ?? 0}>
        {#if item.kind === 'bubble'}
          <FlowBubble {item} {lane} />
        {:else}
          <FlowCard {item} lanes={feed.lanes} />
        {/if}
      </li>
    {/each}
  </ol>
</div>
