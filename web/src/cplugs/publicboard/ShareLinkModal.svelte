<script lang="ts">
  import { onDestroy } from 'svelte';
  import { copyToClipboard, t } from '../sdk';
  import { Button, ConfirmPopup, Field, IconButton, List, ListRow, ModalShell, RadioGroup, Tag } from '../sdk/ui';
  import type { RadioOption } from '../sdk/ui';
  import { MODES, TTLS, isMode, isTtl, linkUrl, listLinks, mintLink, publicHost, refusalReason, revokeBoardLinks, revokeLink, type LinkRow } from './links-api';
  import './share-link.css';

  let { slug, close }: { slug: string; close: (value: null) => void } = $props();

  const DEFAULT_TTL = '1d';
  const DEFAULT_MODE = 'pinned';
  const COPIED_MS = 1500;

  let ttl = $state<string>(DEFAULT_TTL);
  let mode = $state<string>(DEFAULT_MODE);
  let host = $state<string | null | undefined>(undefined);
  let rows = $state<LinkRow[]>([]);
  let shown = $state<string | null>(null);
  let busy = $state(false);
  let copied = $state(false);
  let asking = $state(false);
  let allKey = $state<HTMLElement | null>(null);
  let notice = $state('');
  let copyTimer: ReturnType<typeof setTimeout> | undefined;

  const ttlOptions: RadioOption[] = TTLS.map((value) => ({ value, label: t(`cplug.publicboard.share.ttl_${value}`) }));
  const modeOptions: RadioOption[] = MODES.map((value) => ({ value, label: t(`cplug.publicboard.share.mode_${value}`), hint: t(`cplug.publicboard.share.mode_${value}_hint`) }));
  const ready = $derived(host !== undefined);
  const anyActive = $derived(rows.some((row) => row.status === 'active'));

  async function refresh(): Promise<void> {
    try {
      rows = await listLinks(slug);
    } catch (error) {
      notice = t('cplug.publicboard.share.list_failed', { reason: refusalReason(error) });
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
    if (busy || !host || !isTtl(ttl) || !isMode(mode)) return;
    busy = true;
    notice = '';
    try {
      const made = await mintLink(slug, ttl, mode);
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
      notice = t('cplug.publicboard.share.remove_failed', { reason: refusalReason(error) });
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
      notice = t('cplug.publicboard.share.remove_failed', { reason: refusalReason(error) });
    } finally {
      busy = false;
    }
  }

  function copy(): void {
    if (!shown) return;
    clearTimeout(copyTimer);
    void copyToClipboard(shown).then((ok) => {
      copied = ok;
      notice = ok ? '' : t('cplug.publicboard.share.copy_manual');
      if (ok) copyTimer = setTimeout(() => (copied = false), COPIED_MS);
    });
  }

  const SHORT_ID = 8;

  function shortId(id: string): string {
    return id.slice(0, SHORT_ID);
  }

  function when(seconds: number): string {
    return `${new Date(seconds * 1000).toISOString().slice(0, 16).replace('T', ' ')} utc`;
  }
</script>

<ModalShell title={t('cplug.publicboard.share.title')} overlayClass="text-prompt-modal pbs-modal" onCancel={() => close(null)} data-board-share-modal>
  {#snippet head()}
    <div class="text-prompt-modal__head"><span class="text-prompt-modal__verb">{t('cplug.publicboard.share.title')}</span></div>
  {/snippet}
  {#snippet children()}
    <p class="pbs-explain">{t('cplug.publicboard.share.explain')}</p>

    {#if shown}
      <div class="pbs-once" data-share-once>
        <Field label={t('cplug.publicboard.share.link')} value={shown} readonly data-share-url />
        <p class="pbs-warn" role="status">{t('cplug.publicboard.share.once')}</p>
        <div class="pbs-actions">
          <Button variant="confirm" data-share-copy onclick={copy}>{copied ? t('cplug.publicboard.share.copied') : t('cplug.publicboard.share.copy')}</Button>
          <Button data-share-another onclick={() => { shown = null; copied = false; notice = ''; }}>{t('cplug.publicboard.share.another')}</Button>
        </div>
      </div>
    {:else}
      <h4 class="pbs-label" id="pbs-ttl-label">{t('cplug.publicboard.share.ttl')}</h4>
      <RadioGroup labelledby="pbs-ttl-label" orientation="horizontal" options={ttlOptions} bind:value={ttl} />
      <h4 class="pbs-label" id="pbs-mode-label">{t('cplug.publicboard.share.mode')}</h4>
      <RadioGroup labelledby="pbs-mode-label" options={modeOptions} bind:value={mode} />
      {#if ready && !host}<p class="pbs-warn" role="status" data-share-no-host>{t('cplug.publicboard.share.no_host')}</p>{/if}
      <div class="pbs-actions">
        <Button variant="confirm" data-share-create disabled={busy || !host} onclick={() => void create()}>{busy ? t('cplug.publicboard.share.making') : t('cplug.publicboard.share.create')}</Button>
      </div>
    {/if}

    {#if notice}<p class="pbs-error" role="alert" data-share-notice>{notice}</p>{/if}

    <h4 class="pbs-label">{t('cplug.publicboard.share.links')}</h4>
    {#if rows.length === 0}
      <p class="pbs-none">{t('cplug.publicboard.share.none')}</p>
    {:else}
      <List label={t('cplug.publicboard.share.links')} density="dense">
        {#snippet children()}
          {#each rows as row (row.id)}
            <ListRow primary={shortId(row.id)} data-share-row={row.id}>
              {#snippet below()}{t(`cplug.publicboard.share.mode_${row.mode}`)} · {t('cplug.publicboard.share.expires', { when: when(row.expires_at) })}{/snippet}
              {#snippet actions()}
                <Tag tone={row.status === 'active' ? 'ok' : 'neutral'}>{t(`cplug.publicboard.share.status_${row.status}`)}</Tag>
                {#if row.status === 'active'}
                  <span class="pbs-remove">
                    <IconButton label={t('cplug.publicboard.share.remove')} icon="trash" variant="danger" iconSize={14} disabled={busy} data-share-remove={row.id}
                                onclick={() => void remove(row.id)} />
                  </span>
                {/if}
              {/snippet}
            </ListRow>
          {/each}
        {/snippet}
      </List>
      {#if anyActive}
        <div class="pbs-actions">
          <Button variant="danger" size="sm" data-share-remove-all bind:element={allKey} disabled={busy} onclick={() => (asking = !asking)}>{t('cplug.publicboard.share.remove_all')}</Button>
        </div>
      {/if}
    {/if}
    {#if asking}
      <ConfirmPopup label={t('cplug.publicboard.share.remove_all')} message={t('cplug.publicboard.share.remove_all_confirm')} anchor={allKey}
                    cancelLabel={t('cplug.publicboard.share.cancel')} confirmLabel={t('cplug.publicboard.share.remove_all_go')}
                    data-share-remove-all-confirm confirmProps={{ 'data-share-remove-all-go': '' }}
                    onConfirm={() => void removeAll()} onCancel={() => (asking = false)} />
    {/if}
  {/snippet}
  {#snippet footer()}
    <Button data-share-close onclick={() => close(null)}>{t('cplug.publicboard.share.close')}</Button>
  {/snippet}
</ModalShell>
