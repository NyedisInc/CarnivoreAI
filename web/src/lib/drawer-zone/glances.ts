import { ledger } from '../../opscenter/api';
import { accountSwitch } from '../account-switch/switch-store.svelte';
import { providerGlanceOptions, providerGlanceTiles, type ProviderGlance } from '../ledger-drawer/glance-tiles';
import ProviderGlanceTile from '../ledger-drawer/ProviderGlanceTile.svelte';
import FilesGlanceTile from '../../opscenter/cells/files/FilesGlanceTile.svelte';
import { registerGlance } from './glance';

registerGlance<ProviderGlance>('core.ledger', {
  tiles: (options) => providerGlanceTiles(ledger.data, Date.now(), options, accountSwitch.data),
  component: ProviderGlanceTile,
  options: () => providerGlanceOptions(ledger.data),
});

registerGlance<null>('core.files', {
  tiles: () => [{ key: 'files', data: null }],
  component: FilesGlanceTile,
});
