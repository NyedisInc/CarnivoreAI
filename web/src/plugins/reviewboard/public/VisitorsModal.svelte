<script lang="ts">
  /* the history bar */
  import { canOpenVisitorRevision, openVisitorRevision, type VisitorRevision } from '../board-visitor-revisions.svelte';
import { t } from '../../sdk';
  import { Button, ConfirmPopup, IconButton, ModalShell, Tag } from '../../sdk/ui';
  import { refusalReason } from './links-api';
  import { forwardVisitors, removeForwarded, removeVisitor, removeVisitorRevision, type VisitorEntry, type VisitorResponse } from './visitors-api';
  import { followVisitors } from './visitors-feed.svelte';
  import './share-link.css';
  import './visitors.css';

  let { slug, close }: { slug: string; close: (value: null) => void } = $props();

  const follow = followVisitors(slug);
  const rows = $derived(follow.feed.rows);
  const loaded = $derived(follow.feed.loaded);
  const answered = $derived(follow.feed.visitors);
  const viewing = $derived(follow.feed.viewing);
  let busy = $state(false);
  let notice = $state('');
  let failed = $state(false);
  const fresh = $derived(rows.filter((row) => row.forwarded_at === null).map((row) => row.id));
  const anyForwarded = $derived(rows.some((row) => row.forwarded_at !== null));
  let asking = $state(false);
  let clearKey = $state<HTMLElement | null>(null);

  async function refresh(): Promise<void> {
    await follow.refresh();
  }

  $effect(() => {
    const error = follow.feed.error;
    if (error !== null) {
      notice = `${t('cplug.reviewboard.public.visitors.list_failed')} ${refusalReason(error)}`;
      failed = true;
    }
  });

  $effect(() => follow.stop);

  async function forward(): Promise<void> {
    if (busy) return;
    busy = true;
    notice = '';
    try {
      const sent = await forwardVisitors(slug, fresh);
      notice = t(sent.left > 0 ? 'cplug.reviewboard.public.visitors.sent_left' : 'cplug.reviewboard.public.visitors.sent', { count: sent.forwarded, messages: sent.messages, left: sent.left });
      failed = false;
      await refresh();
    } catch (error) {
      notice = `${t('cplug.reviewboard.public.visitors.forward_failed')} ${refusalReason(error)}`;
      failed = true;
    } finally {
      busy = false;
    }
  }

  async function removing(act: () => Promise<unknown>): Promise<void> {
    asking = false;
    if (busy) return;
    busy = true;
    notice = '';
    try {
      await act();
      await refresh();
    } catch (error) {
      notice = `${t('cplug.reviewboard.public.visitors.remove_failed')} ${refusalReason(error)}`;
      failed = true;
    } finally {
      busy = false;
    }
  }

  function who(row: VisitorResponse): string {
    return row.name ? t('cplug.reviewboard.public.visitors.named', { name: row.name }) : t('cplug.reviewboard.public.visitors.anonymous');
  }

  function line(entry: VisitorEntry): string {
    const value = entry.picks ? entry.picks.join(', ')
      : entry.checked !== undefined ? t(entry.checked ? 'cplug.reviewboard.public.visitors.yes' : 'cplug.reviewboard.public.visitors.no')
      : (entry.text ?? '');
    return `${entry.label ?? t('cplug.reviewboard.public.visitors.board')}: ${value}`;
  }

  function openRevision(row: VisitorRevision): void {
    if (openVisitorRevision(slug, row.revision, row.number)) close(null);
  }

  function when(seconds: number): string {
    return `${new Date(seconds * 1000).toISOString().slice(0, 16).replace('T', ' ')} utc`;
  }
</script>

<ModalShell look="titlerow" closable={false} title={t('cplug.reviewboard.public.visitors.title')} overlayClass="pbs-vmodal" onCancel={() => close(null)} data-board-visitors-modal>
  {#snippet children()}
    <p class="pbs-explain">{t('cplug.reviewboard.public.visitors.explain')}</p>
    <p class="pbs-explain" data-visitors-lookalike>{t('cplug.reviewboard.public.visitors.lookalike')}</p>
    {#if answered.length > 0}
      <h4 class="pbs-label">{t('cplug.reviewboard.public.visitors.answered')}</h4>
      <div class="pbs-ulist" data-visitors-answered>
        {#each answered as row (`${row.number}:${row.revision}`)}
          <div class="pbs-urow">
            <Button size="sm" data-visitor-revision={row.label} disabled={!canOpenVisitorRevision()} onclick={() => openRevision(row)}>
              <span class="pbs-ubadge">{row.label}</span>
              {#if row.present}<span class="pbs-here" data-visitor-present={row.label}>{t('cplug.reviewboard.public.visitors.here')}</span>{/if}
              <span class="pbs-vmeta">{t('cplug.reviewboard.public.visitors.answered_meta', { revision: row.revision, when: when(row.updated_at) })}</span>
            </Button>
            <IconButton label={t('cplug.reviewboard.public.visitors.remove_answers', { label: row.label, revision: row.revision })} icon="trash" variant="danger"
                        iconSize={14} disabled={busy} data-visitor-revision-remove={`${row.label}:${row.revision}`}
                        onclick={() => void removing(() => removeVisitorRevision(slug, row.number, row.revision))} />
          </div>
        {/each}
      </div>
    {/if}
    {#if viewing > 0}
      <p class="pbs-explain" data-visitors-viewing>{t('cplug.reviewboard.public.visitors.viewing', { count: viewing })}</p>
    {/if}
    {#if loaded && rows.length === 0}
      <p class="pbs-none">{t('cplug.reviewboard.public.visitors.none')}</p>
    {:else}
      <div class="pbs-vlist">
        {#each rows as row (row.id)}
          <section class="pbs-vrow" data-visitor-row={row.id}>
            <div class="pbs-vhead">
              <span class="pbs-vwho">{who(row)}</span>
              <span class="pbs-vmeta">{t('cplug.reviewboard.public.visitors.meta', { kind: t(`cplug.reviewboard.public.visitors.kind_${row.kind}`), revision: row.revision, when: when(row.created_at) })}</span>
              <Tag tone={row.forwarded_at === null ? 'ok' : 'neutral'}>{t(row.forwarded_at === null ? 'cplug.reviewboard.public.visitors.new' : 'cplug.reviewboard.public.visitors.forwarded')}</Tag>
              <span class="pbs-remove">
                <IconButton label={t('cplug.reviewboard.public.visitors.remove')} icon="trash" variant="danger" iconSize={14} disabled={busy} data-visitor-remove={row.id}
                            onclick={() => void removing(() => removeVisitor(row.id))} />
              </span>
            </div>
            {#each row.entries as entry, i (i)}
              <p class="pbs-vline">{line(entry)}</p>
              {#if entry.note}<p class="pbs-vline">{t('cplug.reviewboard.public.visitors.note', { note: entry.note })}</p>{/if}
            {/each}
          </section>
        {/each}
      </div>
    {/if}
    <p class="pbs-explain">{t('cplug.reviewboard.public.visitors.forward_hint')}</p>
    <div class="pbs-actions">
      <Button variant="confirm" data-visitors-forward disabled={busy || (fresh.length === 0 && answered.length === 0)} onclick={() => void forward()}>
        {busy ? t('cplug.reviewboard.public.visitors.forwarding') : t('cplug.reviewboard.public.visitors.forward')}
      </Button>
      {#if anyForwarded}
        <Button variant="danger" size="sm" data-visitors-remove-forwarded bind:element={clearKey} disabled={busy} onclick={() => (asking = !asking)}>
          {t('cplug.reviewboard.public.visitors.remove_forwarded')}
        </Button>
      {/if}
    </div>
    {#if asking}
      <ConfirmPopup label={t('cplug.reviewboard.public.visitors.remove_forwarded')} message={t('cplug.reviewboard.public.visitors.remove_forwarded_confirm')} anchor={clearKey}
                    cancelLabel={t('cplug.reviewboard.public.visitors.cancel')} confirmLabel={t('cplug.reviewboard.public.visitors.remove_forwarded_go')}
                    confirmProps={{ 'data-visitors-remove-forwarded-go': '' }}
                    onConfirm={() => void removing(() => removeForwarded(slug))} onCancel={() => (asking = false)} />
    {/if}
    {#if notice}<p class={failed ? 'pbs-error' : 'pbs-warn'} role={failed ? 'alert' : 'status'} data-visitors-notice>{notice}</p>{/if}
  {/snippet}
  {#snippet footer()}
    <Button data-visitors-refresh disabled={busy} onclick={() => void refresh()}>{t('cplug.reviewboard.public.visitors.refresh')}</Button>
    <Button data-visitors-close onclick={() => close(null)}>{t('cplug.reviewboard.public.visitors.close')}</Button>
  {/snippet}
</ModalShell>
