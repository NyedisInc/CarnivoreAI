<script lang="ts">
  import { Button } from '../base';
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
  const { offers, picked, busy, attr, onLook, onYes, onNo }: Props = $props();
</script>

<Button {...{ [attr]: 'look' }} disabled={busy} onclick={onLook}>{t('first_run.join.look')}</Button>
{#if offers.length > 0}
  <ul class="pack-offers">
    {#each offers as offer (offer.fid)}
      <li class="pack-offers__row" {...{ [attr]: 'offer' }}>
        <p class="pack-offers__text">{t('first_run.join.offer', { label: offer.label })}</p>
        <div class="pack-offers__actions">
          <Button {...{ [attr]: 'offer-no' }} onclick={() => onNo(offer)}>{t('first_run.join.offer_no')}</Button>
          <Button variant="confirm" {...{ [attr]: 'offer-yes' }} aria-pressed={picked === offer.fid} onclick={() => onYes(offer)}>{t('first_run.join.offer_yes')}</Button>
        </div>
      </li>
    {/each}
  </ul>
{/if}
