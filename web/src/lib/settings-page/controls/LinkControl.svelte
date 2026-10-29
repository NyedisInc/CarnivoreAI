
<script lang="ts">
    import Button from '../../base/Button.svelte';
    import type { Translate } from '../../sessions/types';
    import type { LinkAction } from '../settings-registry';
    import { settingsView } from '../settings-view.svelte';

    interface Props {
        action: LinkAction;
        t: Translate;
    }

    const { action, t }: Props = $props();

    function open() {
        settingsView.section = 'launch_profiles';
    }
</script>

<Button data-settings-link={action} onclick={open}>
    {t(`settings.link.${action}`)}
</Button>
