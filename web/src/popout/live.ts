import { mountPanel } from '../lib/mount';
import { bootResourcePush } from '../lib/resource-push/boot';
import { startOutbox } from '../lib/outbox/outbox';
import { startVersionWatch } from '../lib/version-watch/version-watch.svelte';
import VersionBanner from '../lib/version-watch/VersionBanner.svelte';
import { startConnectionWatch } from '../lib/live-status/connection.svelte';
import OfflineMarker from '../lib/live-status/OfflineMarker.svelte';

export const POPOUT_VERSION_CONTAINER = 'version-banner-container';

export const POPOUT_OFFLINE_CONTAINER = 'popout-offline-marker';

export function bootPopoutLive(): void {
    bootResourcePush();
    startOutbox();
    startConnectionWatch();
    startVersionWatch({ baselineFromServer: true });
    mountPanel(POPOUT_VERSION_CONTAINER, VersionBanner, {});
    mountPanel(POPOUT_OFFLINE_CONTAINER, OfflineMarker, {});
}
