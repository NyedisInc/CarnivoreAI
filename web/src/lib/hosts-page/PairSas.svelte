
<script lang="ts">
    import type { Translate } from '../sessions/types';

    interface Props {
        t: Translate;
        sas: string;
        label: string;
        fid: string;
        lead: string;
    }

    const { t, sas, label, fid, lead }: Props = $props();
</script>

<p class="modal-description" data-fed-sas-lead>{lead}</p>
<div class="modal-input-group">
    <span class="modal-label">{t('hosts.sas.value_label')}</span>
    <code class="fed-sas" data-fed-sas>{sas}</code>
    <div class="modal-description" data-fed-sas-peer>{t('hosts.sas.peer', { label: label || '?', fid })}</div>
</div>

<style>
  @layer components {
    .fed-sas {
        display: block;
        padding: 10px 8px;
        background: var(--oc-ground-field);
        border: 1px solid var(--oc-line-panel);
        border-radius: var(--oc-radius-sm);
        color: var(--oc-text-bright);
        font-family: var(--font-mono);
        font-size: calc(var(--oc-fs-title) * 1.6);
        letter-spacing: 0.18em;
        text-align: center;
        user-select: all;
    }
  }
</style>
