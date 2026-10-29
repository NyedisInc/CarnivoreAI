import { registerCplugPage } from '../../cplugs/sdk/pages';
import { openPluginSettings } from './screen-host';

registerCplugPage('huddle', () => openPluginSettings('huddle'));
