
<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import Check from '../../opscenter/ui/Check.svelte';
  import { offerLabel, type ConsentOffer } from './relay-consent-store.svelte';

  interface Props {
    offers: readonly ConsentOffer[];
    ticked: string[];
    all: boolean;
    disabled?: boolean;
    idBase: string;
    onedit?: () => void;
  }

  let { offers, ticked = $bindable(), all = $bindable(), disabled = false, idBase, onedit }: Props = $props();

  function toggle(key: string, next: boolean): void {
    ticked = next ? [...ticked.filter((k) => k !== key), key] : ticked.filter((k) => k !== key);
    if (!next) all = false;
    onedit?.();
  }

  function toggleAll(next: boolean): void {
    all = next;
    ticked = next ? offers.map((o) => o.key) : [];
    onedit?.();
  }
</script>

<div class="rc-list" data-rc="list">
  {#each offers as offer (offer.key)}
    <Check label={offerLabel(offer)} checked={ticked.includes(offer.key)} {disabled} id={`${idBase}-${offer.key}`}
      data-rc-key={offer.key} onToggle={(next) => toggle(offer.key, next)} />
  {/each}
  <Check label={t('pack.consent.all')} checked={all} {disabled} id={`${idBase}-all`} data-rc="all" onToggle={toggleAll}
    hint={t('pack.consent.all_hint')} />
</div>
