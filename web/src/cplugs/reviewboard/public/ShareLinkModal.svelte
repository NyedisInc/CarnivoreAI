<script lang="ts">
  import { onDestroy } from 'svelte';
  import { copyToClipboard, t } from '../../sdk';
  import { Button, ConfirmPopup, Field, IconButton, List, ListRow, ModalShell, RadioGroup, Tag } from '../../sdk/ui';
  import type { RadioOption } from '../../sdk/ui';
  import { ACCESSES, MODES, TTLS, clearEndedLinks, fetchLinkToken, isAccess, isMode, isTtl, linkUrl, listLinks, mintLink, ownerPalette, publicHost, refusalReason, revokeBoardLinks, revokeLink, type LinkRow } from './links-api';
  import './share-link.css';

  let { slug, close }: { slug: string; close: (value: null) => void } = $props();

  const DEFAULT_TTL = '1d';
  const DEFAULT_MODE = 'pinned';
  const DEFAULT_ACCESS = 'answer';
  const COPIED_MS = 1500;

  let ttl = $state<string>(DEFAULT_TTL);
  let mode = $state<string>(DEFAULT_MODE);
  let access = $state<string>(DEFAULT_ACCESS);
  let host = $state<string | null | undefined>(undefined);
  let rows = $state<LinkRow[]>([]);
  let shown = $state<string | null>(null);
  let busy = $state(false);
  let copied = $state(false);
  let asking = $state(false);
  let allKey = $state<HTMLElement | null>(null);
  let notice = $state('');
  let copyTimer: ReturnType<typeof setTimeout> | undefined;

  const ttlOptions: RadioOption[] = TTLS.map((value) => ({ value, label: t(`cplug.reviewboard.public.share.ttl_${value}`) }));
  const modeOptions: RadioOption[] = MODES.map((value) => ({ value, label: t(`cplug.reviewboard.public.share.mode_${value}`), hint: t(`cplug.reviewboard.public.share.mode_${value}_hint`) }));
  const accessOptions: RadioOption[] = ACCESSES.map((value) => ({ value, label: t(`cplug.reviewboard.public.share.access_${value}`), hint: t(`cplug.reviewboard.public.share.access_${value}_hint`) }));
  const ready = $derived(host !== undefined);
  const anyActive = $derived(rows.some((row) => row.status === 'active'));
  const anyEnded = $derived(rows.some((row) => row.status !== 'active'));

  async function refresh(): Promise<void> {
    try {
      rows = await listLinks(slug);
    } catch (error) {
      notice = t('cplug.reviewboard.public.share.list_failed', { reason: refusalReason(error) });
    }
  }

  async function readHost(): Promise<void> {
    try {
      host = await publicHost();
    } catch {
      host = null;
    }
  }

  $effect(() => {
    void readHost();
    void refresh();
  });

  onDestroy(() => clearTimeout(copyTimer));

  async function create(): Promise<void> {
    if (busy || !host || !isTtl(ttl) || !isMode(mode) || !isAccess(access)) return;
    busy = true;
    notice = '';
    try {
      const made = await mintLink(slug, ttl, mode, access, ownerPalette());
      shown = linkUrl(host, made.token);
      copied = false;
      await refresh();
    } catch (error) {
      notice = refusalReason(error);
    } finally {
      busy = false;
    }
  }

  async function remove(id: string): Promise<void> {
    if (busy) return;
    busy = true;
    notice = '';
    try {
      await revokeLink(id);
      await refresh();
    } catch (error) {
      notice = t('cplug.reviewboard.public.share.remove_failed', { reason: refusalReason(error) });
    } finally {
      busy = false;
    }
  }

  async function removeAll(): Promise<void> {
    asking = false;
    if (busy) return;
    busy = true;
    notice = '';
    try {
      await revokeBoardLinks(slug);
      await refresh();
    } catch (error) {
      notice = t('cplug.reviewboard.public.share.remove_failed', { reason: refusalReason(error) });
    } finally {
      busy = false;
    }
  }

  async function clearEnded(): Promise<void> {
    if (busy) return;
    busy = true;
    notice = '';
    try {
      await clearEndedLinks(slug);
      await refresh();
    } catch (error) {
      notice = `${t('cplug.reviewboard.public.share.clear_failed')} ${refusalReason(error)}`;
    } finally {
      busy = false;
    }
  }

  function copy(): void {
    if (!shown) return;
    clearTimeout(copyTimer);
    void copyToClipboard(shown).then((ok) => {
      copied = ok;
      notice = ok ? '' : t('cplug.reviewboard.public.share.copy_manual');
      if (ok) copyTimer = setTimeout(() => (copied = false), COPIED_MS);
    });
  }

  /* from the owner */
  async function copyRow(id: string): Promise<void> {
    if (busy || !host) return;
    notice = '';
    try {
      const ok = await copyToClipboard(linkUrl(host, await fetchLinkToken(id)));
      notice = ok ? t('cplug.reviewboard.public.share.copied_row') : t('cplug.reviewboard.public.share.copy_manual_row');
    } catch (error) {
      notice = `${t('cplug.reviewboard.public.share.copy_failed')} ${refusalReason(error)}`;
    }
  }

  const SHORT_ID = 8;

  function shortId(id: string): string {
    return id.slice(0, SHORT_ID);
  }

  function when(seconds: number): string {
    return `${new Date(seconds * 1000).toISOString().slice(0, 16).replace('T', ' ')} utc`;
  }
</script>

<ModalShell title={t('cplug.reviewboard.public.share.title')} overlayClass="text-prompt-modal pbs-modal" onCancel={() => close(null)} data-board-share-modal>
  {#snippet head()}
    <div class="text-prompt-modal__head"><span class="text-prompt-modal__verb">{t('cplug.reviewboard.public.share.title')}</span></div>
  {/snippet}
  {#snippet children()}
    <p class="pbs-explain">{t('cplug.reviewboard.public.share.explain')}</p>

    {#if shown}
      <div class="pbs-once" data-share-once>
        <Field label={t('cplug.reviewboard.public.share.link')} value={shown} readonly data-share-url />
        <p class="pbs-warn" role="status">{t('cplug.reviewboard.public.share.once')}</p>
        <div class="pbs-actions">
          <Button variant="confirm" data-share-copy onclick={copy}>{copied ? t('cplug.reviewboard.public.share.copied') : t('cplug.reviewboard.public.share.copy')}</Button>
          <Button data-share-another onclick={() => { shown = null; copied = false; notice = ''; }}>{t('cplug.reviewboard.public.share.another')}</Button>
        </div>
      </div>
    {:else}
      <h4 class="pbs-label" id="pbs-ttl-label">{t('cplug.reviewboard.public.share.ttl')}</h4>
      <RadioGroup labelledby="pbs-ttl-label" orientation="horizontal" options={ttlOptions} bind:value={ttl} />
      <h4 class="pbs-label" id="pbs-mode-label">{t('cplug.reviewboard.public.share.mode')}</h4>
      <RadioGroup labelledby="pbs-mode-label" options={modeOptions} bind:value={mode} />
      <h4 class="pbs-label" id="pbs-access-label">{t('cplug.reviewboard.public.share.access')}</h4>
      <RadioGroup labelledby="pbs-access-label" options={accessOptions} bind:value={access} />
      {#if ready && !host}<p class="pbs-warn" role="status" data-share-no-host>{t('cplug.reviewboard.public.share.no_host')}</p>{/if}
      <div class="pbs-actions">
        <Button variant="confirm" data-share-create disabled={busy || !host} onclick={() => void create()}>{busy ? t('cplug.reviewboard.public.share.making') : t('cplug.reviewboard.public.share.create')}</Button>
      </div>
    {/if}

    {#if notice}<p class="pbs-error" role="alert" data-share-notice>{notice}</p>{/if}

    <h4 class="pbs-label">{t('cplug.reviewboard.public.share.links')}</h4>
    {#if rows.length === 0}
      <p class="pbs-none">{t('cplug.reviewboard.public.share.none')}</p>
    {:else}
      <List label={t('cplug.reviewboard.public.share.links')} density="dense">
        {#snippet children()}
          {#each rows as row (row.id)}
            <ListRow primary={shortId(row.id)} data-share-row={row.id}>
              {#snippet below()}{t(`cplug.reviewboard.public.share.mode_${row.mode}`)} · {t(`cplug.reviewboard.public.share.access_${row.access ?? 'answer'}`)} · {t('cplug.reviewboard.public.share.expires', { when: when(row.expires_at) })}{#if row.status === 'active' && !row.copyable}{` · ${t('cplug.reviewboard.public.share.not_copyable')}`}{/if}{/snippet}
              {#snippet actions()}
                <Tag tone={row.status === 'active' ? 'ok' : 'neutral'}>{t(`cplug.reviewboard.public.share.status_${row.status}`)}</Tag>
                {#if row.status === 'active' && row.copyable}
                  <span class="pbs-remove">
                    <IconButton label={t('cplug.reviewboard.public.share.copy_row')} icon="copy" iconSize={14} disabled={busy || !host} data-share-copy-row={row.id}
                                onclick={() => void copyRow(row.id)} />
                  </span>
                {/if}
                {#if row.status === 'active'}
                  <span class="pbs-remove">
                    <IconButton label={t('cplug.reviewboard.public.share.remove')} icon="trash" variant="danger" iconSize={14} disabled={busy} data-share-remove={row.id}
                                onclick={() => void remove(row.id)} />
                  </span>
                {/if}
              {/snippet}
            </ListRow>
          {/each}
        {/snippet}
      </List>
      {#if anyActive || anyEnded}
        <div class="pbs-actions">
          {#if anyActive}
            <Button variant="danger" size="sm" data-share-remove-all bind:element={allKey} disabled={busy} onclick={() => (asking = !asking)}>{t('cplug.reviewboard.public.share.remove_all')}</Button>
          {/if}
          {#if anyEnded}
            <Button size="sm" data-share-clear-ended disabled={busy} onclick={() => void clearEnded()}>{t('cplug.reviewboard.public.share.clear_ended')}</Button>
          {/if}
        </div>
      {/if}
    {/if}
    {#if asking}
      <ConfirmPopup label={t('cplug.reviewboard.public.share.remove_all')} message={t('cplug.reviewboard.public.share.remove_all_confirm')} anchor={allKey}
                    cancelLabel={t('cplug.reviewboard.public.share.cancel')} confirmLabel={t('cplug.reviewboard.public.share.remove_all_go')}
                    data-share-remove-all-confirm confirmProps={{ 'data-share-remove-all-go': '' }}
                    onConfirm={() => void removeAll()} onCancel={() => (asking = false)} />
    {/if}
  {/snippet}
  {#snippet footer()}
    <Button data-share-close onclick={() => close(null)}>{t('cplug.reviewboard.public.share.close')}</Button>
  {/snippet}
</ModalShell>
