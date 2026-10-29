<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import './pack-offers.css';

  interface Offer { readonly fid: string; readonly label: string }
  interface Props {
    offers: readonly Offer[];
    picked: string | null;
    busy: boolean;
    attr: 'data-first-run' | 'data-cmp';
    btn?: string;
    btnConfirm?: string;
    onLook: () => void;
    onYes: (offer: Offer) => void;
    onNo: (offer: Offer) => void;
  }
  const { offers, picked, busy, attr, btn = 'oc-btn', btnConfirm = 'oc-btn oc-btn--confirm', onLook, onYes, onNo }: Props = $props();
</script>

<button type="button" class={btn} {...{ [attr]: 'look' }} disabled={busy} onclick={onLook}>{t('first_run.join.look')}</button>
{#if offers.length > 0}
  <ul class="pack-offers">
    {#each offers as offer (offer.fid)}
      <li class="pack-offers__row" {...{ [attr]: 'offer' }}>
        <p class="pack-offers__text">{t('first_run.join.offer', { label: offer.label })}</p>
        <div class="pack-offers__actions">
          <button type="button" class={btn} {...{ [attr]: 'offer-no' }} onclick={() => onNo(offer)}>{t('first_run.join.offer_no')}</button>
          <button type="button" class={btnConfirm} {...{ [attr]: 'offer-yes' }} aria-pressed={picked === offer.fid} onclick={() => onYes(offer)}>{t('first_run.join.offer_yes')}</button>
        </div>
      </li>
    {/each}
  </ul>
{/if}
