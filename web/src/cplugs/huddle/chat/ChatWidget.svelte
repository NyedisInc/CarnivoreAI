<script lang="ts">
  import { tick, untrack } from 'svelte';
  import { ApiError, sessionRow, t } from '../../sdk';
  import { Icon, TaskMark } from '../../sdk/ui';
  import { postOrder } from './chat-api';
  import { agentIdOf, awaitingReply, cardLineId, chatRows, composerCap, composerGhost, eventLabel, fallbackText, headOf, needsOwner, questionOf, quoteOf, quotedOrder, recipientOf, tabAccepts, visibleEntries, waitingCount, type BurstParty, type ChatQuote } from './chat-model';
  import { reducedMotion } from '../swarm/characters/reduced-motion.svelte';
  import { rosterIdOfName, rosterIdOfUuid } from './chat-avatar';
  import { reply } from '../huddle.svelte';
  import { createNodeLooks } from '../swarm/node-looks.svelte';
  import ChatBar from './ChatBar.svelte';
  import { elapsed } from '../huddle-progress';
  import ChatAvatar from './ChatAvatar.svelte';
  import AuthorPath from './AuthorPath.svelte';
  import { createChatStore, type ChatStore } from './chat-store.svelte';
  import ChatCard from './ChatCard.svelte';
  import ChatMarkdown from './ChatMarkdown.svelte';
  import EventCard from './EventCard.svelte';
  import TrafficCard from './TrafficCard.svelte';
  import { IconButton } from '../../sdk/ui';
  import TaskManagerChips from '../TaskManagerChips.svelte';
  import { createAttachments } from '../task-manager-attachments.svelte';
  import { carriesFiles, filesOf } from '../task-manager-files';
  import { splitSentText, uploadToSession, withPaths } from './chat-upload';
  import ChatSentImages from './ChatSentImages.svelte';

  interface Props {
    instance?: string;
    store?: unknown;
    onOpenedTerminal?: () => void;
    onName?: (name: string) => void;
    titled?: boolean;
    framed?: boolean;
    chat?: ChatStore | null;
    waitingOnly?: boolean;
    notice?: string;
  }

  let {
    instance, store, onOpenedTerminal, onName, titled = false, framed = false, chat: given = null,
    waitingOnly = $bindable(false), notice = $bindable(''),
  }: Props = $props();

  const agentId = $derived(agentIdOf(instance));
  const chat = $derived(given ?? (agentId === null ? null : createChatStore(agentId)));
  const view = $derived(chat?.state ?? { agent: null, entries: [], status: 'error' as const });
  const agent = $derived(view.agent);
  const name = $derived(agent?.display_name ?? '');
  const shown = $derived(visibleEntries(view.entries, waitingOnly));
  const waiting = $derived(waitingCount(view.entries));
  const lookup = { idOfName: rosterIdOfName, idOfUuid: rosterIdOfUuid };
  const rows = $derived(chatRows(shown, { id: agentId, name }, lookup));
  const looks = createNodeLooks();

  let draft = $state('');
  let sending = $state(false);
  let quote = $state<ChatQuote | null>(null);
  let input = $state<HTMLTextAreaElement | null>(null);
  let scroller = $state<HTMLElement | null>(null);
  let section = $state<HTMLElement | null>(null);
  const ready = $derived(!!draft.trim() || attached.ids.length > 0);
  let picker = $state<HTMLInputElement | null>(null);
  let dropping = $state(false);

  const thinking = $derived(agentId !== null && awaitingReply(view.entries));
  const selfParty = $derived<BurstParty>({ key: `self:${agentId}`, dir: null, path: [{ kind: 'agent', name, agent_id: agentId }], agentId, sessionUuid: null, owner: false });
  const still = $derived(reducedMotion());

  const sessionId = $derived(agent?.session_id ?? null);
  const attached = createAttachments((file) => uploadToSession(sessionId as string, file));
  const suggestion = $derived(sessionRow(sessionId)?.prompt_suggestion ?? null);
  const ghost = $derived(composerGhost(draft, suggestion));

  $effect(() => {
    const current = chat;
    return current && !given ? current.start() : undefined;
  });

  let now = $state(Date.now());
  const ticks = $derived(shown.some((entry) => headOf(entry) !== null));
  $effect(() => {
    if (!ticks) return undefined;
    now = Date.now();
    const timer = setInterval(() => (now = Date.now()), 30_000);
    return () => clearInterval(timer);
  });

  $effect(() => {
    onName?.(name);
  });

  function fit(): void {
    if (!input || !section) return;
    const stick = !!scroller && scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 4;
    const style = getComputedStyle(input);
    const px = (value: string): number => parseFloat(value) || 0;
    const frame = px(style.borderTopWidth) + px(style.borderBottomWidth);
    const line = px(style.lineHeight) || px(style.fontSize) * 1.45;
    input.style.height = 'auto';
    const want = input.scrollHeight + frame;
    const cap = composerCap(line, px(style.paddingTop) + px(style.paddingBottom) + frame, section.clientHeight);
    input.style.height = `${Math.min(want, cap)}px`;
    input.style.overflowY = want > cap ? 'auto' : 'hidden';
    if (stick && scroller) scroller.scrollTop = scroller.scrollHeight;
  }

  $effect(() => {
    void draft;
    fit();
  });

  const PIN_SLACK_PX = 4;
  let pinned = $state(true);
  let unseen = $state(0);
  let jumping = false;
  let counted = 0;
  $effect(() => {
    const count = view.entries.length;
    const follow = pinned;
    untrack(() => {
      const added = Math.max(0, count - counted);
      counted = count;
      if (follow) void tick().then(() => pinned && scroller && (scroller.scrollTop = scroller.scrollHeight));
      else unseen += added;
    });
  });

  $effect(() => {
    void agentId;
    pinned = true;
    unseen = 0;
  });

  function onScroll(): void {
    if (!scroller) return;
    const bottom = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight <= PIN_SLACK_PX;
    if (jumping && !bottom) return;
    jumping = false;
    pinned = bottom;
    if (bottom) unseen = 0;
  }

  function jumpToLatest(): void {
    if (!scroller) return;
    jumping = !still;
    pinned = true;
    unseen = 0;
    scroller.scrollTo({ top: scroller.scrollHeight, behavior: still ? 'auto' : 'smooth' });
  }

  function partyName(party: BurstParty): string {
    const crumb = party.path[party.path.length - 1];
    return party.owner ? t('cplug.huddle.chat.you') : (crumb?.name ?? '');
  }

  function foldKinds(entries: readonly { kind: string; event?: string }[]): string {
    return [...new Set(entries.map((e) => eventLabel(e.event ?? '', t)).filter(Boolean))].join(', ');
  }

  function failure(error: unknown, key: string): string {
    return error instanceof ApiError && error.message ? error.message : t(key);
  }

  async function send(): Promise<void> {
    const typed = draft.trim();
    if ((!typed && attached.ids.length === 0) || sending || attached.busy || agentId === null) return;
    const text = withPaths(typed, attached.ids);
    sending = true;
    notice = '';
    try {
      if (quote?.item) {
        if (!(await reply(quote.item, text, [], false))) throw new Error('');
      } else {
        const outcome = await postOrder(agentId, quote ? quotedOrder(quote, text) : text);
        if (outcome.outcome === 'waking') notice = t('cplug.huddle.chat.sent_waking');
      }
      draft = '';
      pinned = true;
      attached.clear();
      quote = null;
      await chat?.refresh();
    } catch (error) {
      notice = failure(error, 'cplug.huddle.chat.send_failed');
    }
    sending = false;
  }

  function onPaste(event: ClipboardEvent): void {
    const files = filesOf(event.clipboardData);
    if (!sessionId || files.length === 0) return;
    event.preventDefault();
    attached.add(files);
  }

  function onDragOver(event: DragEvent): void {
    if (!sessionId || !carriesFiles(event.dataTransfer)) return;
    event.preventDefault();
    dropping = true;
  }

  function onDrop(event: DragEvent): void {
    dropping = false;
    const files = filesOf(event.dataTransfer);
    if (!sessionId || files.length === 0) return;
    event.preventDefault();
    attached.add(files);
  }

  function onPick(): void {
    if (picker?.files) attached.add(Array.from(picker.files));
    if (picker) picker.value = '';
  }

  function onKeydown(event: KeyboardEvent): void {
    const taken = event.isComposing || event.shiftKey ? null : tabAccepts(event.key, draft, suggestion);
    if (taken !== null) {
      event.preventDefault();
      draft = taken;
      void tick().then(() => input?.setSelectionRange(taken.length, taken.length));
      return;
    }
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      void send();
    }
  }

  function quoteEntry(entry: Parameters<typeof quoteOf>[0]): void {
    quote = quoteOf(entry);
    void tick().then(() => input?.focus());
  }
</script>

<section class="hdc" bind:this={section} data-chat-agent={agentId ?? undefined} data-chat-state={view.status}>
  {#if !framed}
    <ChatBar {agentId} {agent} {chat} bind:waitingOnly {waiting} {store} {onOpenedTerminal} {titled} onNotice={(text) => (notice = text)} />
  {/if}
  {#if agent?.placement_reason}
    <p class="hdc-placed" data-chat-placed>
      {t('cplug.huddle.chat.placed', { computer: agent.host_key && agent.host_key !== 'local' && agent.host_label ? agent.host_label : t('cplug.huddle.chat.placed_here'), reason: agent.placement_reason })}
    </p>
  {/if}

  <div class="hdc-pane">
  <div class="hdc-scroll" bind:this={scroller} onscroll={onScroll} onwheel={() => (jumping = false)} ontouchstart={() => (jumping = false)}>
    {#if agentId === null}
      <p class="hdc-note">{t('cplug.huddle.chat.no_agent')}</p>
    {:else if view.status === 'loading'}
      <p class="hdc-note">{t('cplug.huddle.chat.loading')}</p>
    {:else if view.status === 'error' && !agent}
      <p class="hdc-note">{t('cplug.huddle.chat.error')}</p>
    {:else if shown.length === 0}
      <p class="hdc-note">{waitingOnly ? t('cplug.huddle.chat.filter_empty') : t('cplug.huddle.chat.empty')}</p>
    {:else}
      <ol class="hdc-list">
        {#each rows as row (row.kind === 'fold' ? row.id : row.entry.id)}
          {#if row.kind === 'fold'}
            <li class="hdc-fold-row" data-chat-fold={row.entries.length}>
              <details class="hdc-fold">
                <summary class="hdc-fold-sum">
                  <span class="hdc-fold-caret" aria-hidden="true"><Icon name="chevron-down" size={10} /></span>
                  <span class="hdc-fold-count">{t('cplug.huddle.chat.fold.events', { count: row.entries.length })}</span>
                  <span class="hdc-fold-kinds">{foldKinds(row.entries)}</span>
                </summary>
                <ol class="hdc-fold-list">
                  {#each row.entries as entry (entry.id)}
                    {#if entry.kind === 'event'}
                      <li class="hdc-entry" data-chat-entry="event" data-entry-id={entry.id}><EventCard event={entry.event} text={entry.text} cardId={cardLineId(entry)} /></li>
                    {/if}
                  {/each}
                </ol>
              </details>
            </li>
          {:else}
            {@const entry = row.entry}
            {@const party = row.party}
            {@const head = headOf(entry)}
            <li class="hdc-entry hdc-burst" class:hdc-burst--first={row.first} class:hdc-burst--plain={!party}
                class:hdc-burst--needs={needsOwner(entry) || questionOf(entry) !== null}
                data-chat-entry={entry.kind} data-entry-id={entry.id} data-chat-burst={party ? (row.first ? 'head' : 'follow') : undefined}>
              {#if party}
                <div class="hdc-burst-gutter">
                  {#if row.first}<ChatAvatar {party} name={partyName(party)} {looks} link />{/if}
                  
                  {#if row.at > 0 && (!row.first || !party.dir)}<time class="hdc-burst-time" data-chat-burst-time>{elapsed(now / 1000 - row.at)}</time>{/if}
                </div>
              {/if}
              <div class="hdc-burst-body">
                {#snippet headRow()}{#if party?.dir && row.first}<AuthorPath path={party.path} at={row.at} more={head?.more ?? 0} {now} lead />{/if}{/snippet}
                {#if entry.kind === 'card'}
                  <ChatCard item={entry.item} card={entry.card} agentName={name} question={questionOf(entry)} head={headRow} {now} />
                {:else if entry.kind === 'owner' || entry.kind === 'agent'}
                  <div class="hdc-msg hdc-msg--{entry.kind}">
                    {#if party}{@render headRow()}{:else}<span class="hdc-who">{#if entry.kind === 'owner'}{t('cplug.huddle.chat.you')}{:else}<TaskMark rank={agent?.rank} />{name}{/if}</span>{/if}
                    {#if entry.kind === 'agent'}<div class="hdc-text"><ChatMarkdown source={entry.text} /></div>
                      {#if entry.draft}<span class="hdc-draft" class:hdc-draft--stopped={entry.draft === 'stopped'} data-chat-draft={entry.draft}>{t(entry.draft === 'stopped' ? 'cplug.huddle.chat.draft.stopped' : 'cplug.huddle.chat.draft.writing')}</span>{/if}
                    {:else}
                      {@const sent = sessionId ? splitSentText(entry.text) : { text: entry.text, images: [] }}
                      {#if sent.text}<p class="hdc-text hdc-text--plain">{sent.text}</p>{/if}
                      {#if sessionId && sent.images.length}<ChatSentImages {sessionId} paths={sent.images} />{/if}
                    {/if}
                  </div>
                {:else if entry.kind === 'traffic'}
                  <TrafficCard {entry} bare={!!party} head={headRow} to={recipientOf(entry, lookup)} {looks} />
                {:else if entry.kind === 'event'}
                  <EventCard event={entry.event} text={entry.text} cardId={cardLineId(entry)} />
                {:else}
                  {@render headRow()}
                  
                  <EventCard event={String((entry as { kind: string }).kind)} text={fallbackText(entry)} />
                {/if}
              </div>
              {#if entry.kind !== 'event'}
                <button type="button" class="oc-ibtn oc-ibtn--bare hdc-quote" data-chat-quote={entry.id}
                        aria-label={t('cplug.huddle.chat.quote')} title={t('cplug.huddle.chat.quote')} onclick={() => quoteEntry(entry)}>
                  <Icon name="quote" size={12} />
                </button>
              {/if}
            </li>
          {/if}
        {/each}
      </ol>
    {/if}
  </div>
  {#if !pinned}
    <div class="hdc-latest">
      <IconButton label={unseen > 0 ? t('cplug.huddle.chat.latest_new', { count: unseen }) : t('cplug.huddle.chat.latest')}
                  tooltip={t('cplug.huddle.chat.latest')} data-chat-latest data-chat-latest-count={unseen} onclick={jumpToLatest}>
        <Icon name="chevron-down" size={12} />
        {#if unseen > 0}<span class="hdc-latest-count" aria-hidden="true">{unseen}</span>{/if}
      </IconButton>
    </div>
  {/if}
  </div>

  {#if thinking}
    <div class="hdc-thinking" role="status" aria-label={t('cplug.huddle.chat.thinking', { name })} data-chat-thinking>
      <ChatAvatar party={selfParty} {name} {looks} pose="working" />
      <span class="hdc-bubble" class:hdc-bubble--still={still} aria-hidden="true"><i></i><i></i><i></i></span>
    </div>
  {/if}
  {#if notice}<p class="hdc-notice" role="status">{notice}</p>{/if}
  {#if quote}
    <div class="hdc-quoted" data-chat-quoted={quote.entryId} data-quote-item={quote.item?.id ?? undefined}>
      <span class="hdc-quoted-text">{quote.text}</span>
      <button type="button" class="oc-ibtn oc-ibtn--bare hdc-quoted-clear" aria-label={t('cplug.huddle.chat.quote_clear')} onclick={() => (quote = null)}><Icon name="close" size={10} /></button>
    </div>
  {/if}
  <form class="hdc-compose" class:hdc-compose--drop={dropping} data-chat-compose ondragover={onDragOver} ondragleave={() => (dropping = false)} ondrop={onDrop}
        onsubmit={(event) => { event.preventDefault(); void send(); }}>
    {#if attached.chips.length}<TaskManagerChips chips={attached.chips} onRemove={attached.remove} />{/if}
    <textarea class="oc-field hdc-input" rows="2" bind:this={input} bind:value={draft} onkeydown={onKeydown} onpaste={onPaste} maxlength="4000"
              disabled={agentId === null} aria-label={t('cplug.huddle.chat.compose_label', { name })}
              placeholder={ghost || t('cplug.huddle.chat.compose_placeholder', { name })} data-chat-ghost={ghost ? '' : undefined}></textarea>
    
    <div class="hdc-keys">
      {#if sessionId}
        <input type="file" multiple hidden bind:this={picker} onchange={onPick} data-chat-attach-input />
        <IconButton label={t('cplug.huddle.chat.attach')} icon="paperclip" iconSize={14} variant="quiet" data-chat-attach onclick={() => picker?.click()} />
      {/if}
      <button type="submit" class="oc-btn oc-btn--sm hdc-send" class:oc-btn--confirm={ready && !sending && !attached.busy && agentId !== null} disabled={sending || attached.busy || !ready || agentId === null}>{t('cplug.huddle.chat.send')}</button>
    </div>
  </form>
</section>

<style>
  @layer components {
    .hdc {
      display: flex;
      flex-direction: column;
      height: 100%;
      min-height: 0;
      min-width: 0;
      background: var(--oc-ground-page);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-label);
    }

    .hdc-pane {
      position: relative;
      display: flex;
      flex: 1;
      flex-direction: column;
      min-height: 0;
    }

    .hdc-latest {
      position: absolute;
      bottom: var(--oc-space-2);
      left: 50%;
      transform: translateX(-50%);
      --oc-ibtn-size: 24px;
    }

    .hdc-latest :global([data-btn]) {
      width: auto;
      min-width: 24px;
      padding: 0 var(--oc-space-1);
      gap: var(--oc-space-1);
      background: var(--oc-ground-raised);
    }

    .hdc-latest-count {
      color: var(--oc-text-primary);
      font-size: var(--oc-fs-label);
      font-variant-numeric: tabular-nums;
    }

    .hdc-scroll {
      flex: 1;
      min-height: 0;
      overflow-y: auto;
      overscroll-behavior: contain;
      padding: 8px;
    }

    .hdc-list {
      display: flex;
      flex-direction: column;
      gap: 0;
      margin: 0;
      padding: 0;
      list-style: none;
    }

    .hdc-entry { min-width: 0; }

    .hdc-burst {
      display: grid;
      grid-template-columns: 48px minmax(0, 1fr) auto;
      gap: 0 var(--oc-space-2);
      margin-top: var(--oc-space-1);
      padding: var(--oc-space-1) 0;
    }

    .hdc-burst--first { margin-top: var(--oc-space-5); }
    .hdc-list > .hdc-burst:first-child, .hdc-list > .hdc-fold-row:first-child { margin-top: 0; }
    .hdc-burst--plain { grid-template-columns: minmax(0, 1fr) auto; }
    .hdc-burst--plain[data-chat-entry='event'] { margin-left: calc(48px + var(--oc-space-2)); }

    .hdc-burst-gutter {
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: 2px;
      padding-top: 2px;
    }

    .hdc-quote {
      align-self: start;
      color: var(--oc-text-dim);
      opacity: 0.5;
    }

    .hdc-burst:hover .hdc-quote, .hdc-quote:focus-visible { opacity: 1; }
    .hdc-quote:hover { color: var(--oc-text-bright); }

    .hdc-quoted {
      flex: none;
      display: flex;
      align-items: center;
      gap: var(--oc-space-2);
      min-width: 0;
      padding: 4px 8px 4px var(--oc-space-3);
      box-shadow: inset 2px 0 0 var(--oc-cyan), inset 0 1px 0 var(--oc-line-rule);
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-micro);
    }

    .hdc-quoted-text { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .hdc-quoted-clear { flex: none; color: var(--oc-text-dim); }

    .hdc-burst-time {
      padding-top: 3px;
      color: var(--oc-text-dim);
      font-size: var(--oc-fs-micro);
      white-space: nowrap;
    }

    .hdc-burst-body {
      display: flex;
      flex-direction: column;
      gap: var(--oc-space-1);
      min-width: 0;
    }

    .hdc-burst--needs .hdc-burst-body > :global(.hdc-card) {
      padding-left: var(--oc-space-3);
      box-shadow: inset 2px 0 0 var(--oc-yellow);
    }

    .hdc-fold-row {
      margin: var(--oc-space-4) 0 var(--oc-space-1) calc(48px + var(--oc-space-2));
      padding-left: var(--oc-space-3);
      box-shadow: inset 1px 0 0 var(--oc-line-frame);
    }

    .hdc-fold-sum {
      display: flex;
      align-items: center;
      gap: var(--oc-space-2);
      min-width: 0;
      padding: 2px 0;
      color: var(--oc-text-secondary);
      cursor: pointer;
      list-style: none;
    }

    .hdc-fold-sum::-webkit-details-marker { display: none; }
    .hdc-fold-caret { display: inline-flex; flex: none; transform: rotate(-90deg); }
    .hdc-fold[open] .hdc-fold-caret { transform: none; }

    .hdc-fold-count {
      flex: none;
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }

    .hdc-fold-kinds {
      min-width: 0;
      overflow: hidden;
      color: var(--oc-text-dim);
      font-size: var(--oc-fs-micro);
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .hdc-fold-list { margin: 0; padding: 0; list-style: none; }

    .hdc-placed {
      margin: 0;
      padding: 4px 8px;
      color: var(--oc-text-muted);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-micro);
      box-shadow: inset 0 -1px 0 var(--oc-line-faint);
    }

    .hdc-note {
      margin: 0;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-hint);
    }

    .hdc-msg {
      display: flex;
      flex-direction: column;
      gap: 2px;
      min-width: 0;
      padding: 8px 0;
    }

    .hdc-burst:not(.hdc-burst--plain) .hdc-msg { gap: var(--oc-space-2); padding: 0; }

    .hdc-burst .hdc-text {
      font-size: var(--oc-fs-status);
      line-height: 1.65;
    }

    .hdc-burst .hdc-text > :global(*) { line-height: inherit; }

    .hdc-draft {
      color: var(--oc-text-dim);
      font-size: var(--oc-fs-micro);
    }

    .hdc-draft--stopped { color: var(--oc-coral); }

    .hdc-burst .hdc-text > :global(* > p:not(:first-child)),
    .hdc-burst .hdc-text > :global(* > ul:not(:first-child)),
    .hdc-burst .hdc-text > :global(* > ol:not(:first-child)) { margin-top: var(--oc-space-3); }

    .hdc-burst--plain .hdc-msg--agent { box-shadow: inset 0 1px 0 var(--oc-line-faint); }

    .hdc-burst--plain .hdc-msg--owner {
      align-self: flex-end;
      max-width: 88%;
      margin: 8px 0;
      padding: 4px 8px 6px;
      border: 1px solid var(--oc-line-frame);
      border-radius: var(--oc-radius-sm, 2px);
      background: var(--oc-ground-raised);
    }

    .hdc-who {
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }

    .hdc-text {
      margin: 0;
      color: var(--oc-text-primary);
      overflow-wrap: anywhere;
    }

    .hdc-text--plain { white-space: pre-wrap; }

    .hdc-notice {
      flex: none;
      margin: 0;
      padding: 4px 8px;
      color: var(--oc-yellow);
      font-size: var(--oc-fs-hint);
      box-shadow: inset 0 1px 0 var(--oc-line-faint);
    }

    .hdc-compose {
      flex: none;
      display: flex;
      flex-wrap: wrap;
      align-items: flex-end;
      gap: 8px;
      padding: 8px;
      box-shadow: inset 0 1px 0 var(--oc-line-rule);
    }

    .hdc-compose--drop { box-shadow: inset 0 1px 0 var(--oc-orange); }

    .hdc-input { flex: 1; min-width: 0; resize: none; overflow-y: hidden; }

    .hdc-keys {
      flex: none;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: var(--oc-space-1);
    }

    .hdc-thinking {
      flex: none;
      display: grid;
      grid-template-columns: 48px auto;
      justify-content: start;
      align-items: center;
      gap: 0 var(--oc-space-2);
      padding: var(--oc-space-1) var(--oc-space-2);
    }

    .hdc-thinking > :global(:first-child) { justify-self: end; }

    .hdc-bubble {
      position: relative;
      display: inline-flex;
      align-items: center;
      gap: var(--oc-space-0-5);
      padding: var(--oc-space-1) var(--oc-space-1-5);
      border: 1px solid var(--oc-line-frame);
      border-radius: 9px;
      background: var(--oc-ground-raised);
    }

    .hdc-bubble::before {
      content: '';
      position: absolute;
      left: calc(-1 * var(--oc-space-1-5));
      bottom: -1px;
      width: 4px;
      height: 4px;
      border: 1px solid var(--oc-line-frame);
      border-radius: 50%;
      background: var(--oc-ground-raised);
    }

    .hdc-bubble > i {
      width: 4px;
      height: 4px;
      border-radius: 50%;
      background: var(--oc-text-secondary);
      animation: hdc-think 1.2s ease-in-out infinite;
    }

    .hdc-bubble > i:nth-child(2) { animation-delay: 0.15s; }
    .hdc-bubble > i:nth-child(3) { animation-delay: 0.3s; }
    .hdc-bubble--still > i { animation: none; opacity: 0.7; }

    @keyframes hdc-think {
      0%, 60%, 100% { opacity: 0.3; transform: translateY(0); }
      30% { opacity: 1; transform: translateY(-2px); }
    }

    @media (pointer: fine) {
      .hdc :global(.oc-btn) { min-height: 0; }
      .hdc :global(.oc-ibtn) { width: var(--oc-ibtn-size, 20px); height: var(--oc-ibtn-size, 20px); }
    }
  }
</style>
