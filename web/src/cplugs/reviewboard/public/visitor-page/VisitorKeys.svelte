<script lang="ts">
  import { AnchoredPopup } from '../../../sdk/anchored-popup';
  import { newPostId, type PostBody, type PostResult, type PublicAnchor } from './board-client';
  import { t } from './strings';

  interface Props { anchors: PublicAnchor[]; send: (route: 'comments', body: PostBody) => Promise<PostResult> }
  let { anchors, send }: Props = $props();

  const MAX_TEXT = 4000;
  const MAX_NAME = 60;

  type Which = 'name' | 'comment';
  let open = $state<Which | null>(null);
  let name = $state('');
  let comment = $state('');
  let anchor = $state('');
  let busy = $state(false);
  let said = $state<string | null>(null);
  let commentId = newPostId();
  let nameKey = $state<HTMLElement | null>(null);
  let commentKey = $state<HTMLElement | null>(null);

  function toggle(which: Which): void {
    open = open === which ? null : which;
  }

  function close(): void { open = null; }

  async function sendComment(): Promise<void> {
    const text = comment.trim();
    if (!text || busy) return;
    busy = true;
    const who = name.trim();
    const answer = await send('comments', { client_post_id: commentId, ...(who ? { name: who } : {}), text, ...(anchor ? { anchor } : {}) });
    busy = false;
    if (answer.kind === 'received') {
      said = answer.duplicate ? 'cplug.reviewboard.public.page.sent_again' : 'cplug.reviewboard.public.page.sent';
      commentId = newPostId();
      comment = '';
      anchor = '';
      return;
    }
    const own = ['malformed', 'rejected', 'has_secret', 'full', 'read_only', 'stale'].includes(answer.state);
    said = own ? `cplug.reviewboard.public.page.post.${answer.state}` : `cplug.reviewboard.public.page.state.${answer.state}`;
  }
</script>

<span class="pb-keys" data-visitor-keys>
    <button type="button" data-btn="quiet" data-size="icon" class="pb-key" aria-label={t('cplug.reviewboard.public.page.name_key')} title={t('cplug.reviewboard.public.page.name_key')}
            bind:this={nameKey} aria-haspopup="dialog" aria-expanded={open === 'name'} data-set={name.trim() ? '' : undefined} onclick={() => toggle('name')} data-visitor-key="name">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><circle cx="12" cy="8" r="4" /><path d="M4.5 20.5c0-4.1 3.4-6.5 7.5-6.5s7.5 2.4 7.5 6.5" /></svg>
    </button>
    {#if open === 'name'}
      <AnchoredPopup label={t('cplug.reviewboard.public.page.name')} class="pb-pop" anchor={nameKey} onClose={close} escape="window" data-visitor-pop="name">
        <label class="pb-label" for="pbf-name">{t('cplug.reviewboard.public.page.name')}</label>
        <input id="pbf-name" data-field data-size="sm" type="text" maxlength={MAX_NAME} autocomplete="off" bind:value={name} data-visitor-name />
        <p class="pb-hint">{t('cplug.reviewboard.public.page.name_note')}</p>
      </AnchoredPopup>
    {/if}
    <button type="button" data-btn="quiet" data-size="icon" class="pb-key" aria-label={t('cplug.reviewboard.public.page.comment_key')} title={t('cplug.reviewboard.public.page.comment_key')}
            bind:this={commentKey} aria-haspopup="dialog" aria-expanded={open === 'comment'} onclick={() => toggle('comment')} data-visitor-key="comment">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M4 4h16v12H10l-5 5v-5H3V5Z" /></svg>
    </button>
    {#if open === 'comment'}
      <AnchoredPopup label={t('cplug.reviewboard.public.page.comment')} class="pb-pop pb-pop--wide" anchor={commentKey} onClose={close} escape="window" data-visitor-pop="comment" data-visitor-comment>
        <label class="pb-label" for="pbf-comment">{t('cplug.reviewboard.public.page.comment')}</label>
        <textarea id="pbf-comment" class="pbf-text" data-field rows="4" maxlength={MAX_TEXT} bind:value={comment}></textarea>
        {#if anchors.length > 0}
          <label class="pbf-about">
            <span class="pb-hint">{t('cplug.reviewboard.public.page.comment_on')}</span>
            <select data-field data-size="sm" bind:value={anchor} data-visitor-anchor>
              <option value="">{t('cplug.reviewboard.public.page.comment_on_board')}</option>
              {#each anchors as spot (spot.id)}<option value={spot.id}>{spot.label}</option>{/each}
            </select>
          </label>
        {/if}
        <div class="pbf-actions">
          <button type="button" data-btn="confirm" data-size="sm" disabled={busy || !comment.trim()} onclick={() => void sendComment()} data-visitor-send-comment>
            {busy ? t('cplug.reviewboard.public.page.sending') : t('cplug.reviewboard.public.page.send_comment')}
          </button>
          {#if said}<span class="pbf-said" role="status" data-visitor-said>{t(said)}</span>{/if}
        </div>
        <p class="pb-hint">{t('cplug.reviewboard.public.page.private')}</p>
      </AnchoredPopup>
    {/if}
</span>
