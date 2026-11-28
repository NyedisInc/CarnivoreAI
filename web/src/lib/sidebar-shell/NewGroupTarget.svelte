
<script lang="ts">
    import { t } from '../i18n/index.svelte';
    import { NEW_GROUP_ATTR } from './new-group-target';
</script>

<div class="session-sidebar-newgroup" aria-hidden="true" {...{ [NEW_GROUP_ATTR]: '1' }}>{t('sidebar.group.new.drop')}</div>
