import { registerCplugPage } from '../../plugins/sdk/pages';
import { openPluginSettings } from './screen-host';

registerCplugPage('huddle', () => openPluginSettings('huddle'));
