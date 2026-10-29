
<script lang="ts">
    import ItemSettingsPanel from '../../lib/item-settings/ItemSettingsPanel.svelte';
    import { t } from '../../lib/i18n/index.svelte';
    import { everyKindController } from './widgets-fixture';

    const controller = everyKindController();
</script>

<div class="pledger mgr mgr--embedded">
    <div class="oc-page__detail-body">
        <ItemSettingsPanel kind="widget" id="specimen.every-kind" {t} {controller} />
    </div>
</div>
