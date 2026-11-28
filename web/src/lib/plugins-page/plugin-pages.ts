import { registerCplugPage } from '../../plugins/sdk/pages';
import { openPluginSettings } from './screen-host';

interface PluginPageManifest {
    readonly id?: string;
    readonly ui?: { readonly plugins?: readonly string[] };
    readonly surfaces?: { readonly plugins?: readonly string[] };
    readonly settings_schema?: { readonly fields?: Readonly<Record<string, unknown>> };
}

const MANIFESTS = import.meta.glob<PluginPageManifest>(
    '../../../../src/plugins/*/carnivore.toml',
    { eager: true, import: 'default' },
);

for (const manifest of Object.values(MANIFESTS)) {
    const id = manifest?.id;
    if (!id) continue;
    const uiPlugins = manifest.ui?.plugins ?? manifest.surfaces?.plugins ?? [];
    const hasFields = Object.keys(manifest.settings_schema?.fields ?? {}).length > 0;
    if (hasFields || uiPlugins.includes('settings-panel')) {
        registerCplugPage(id, () => openPluginSettings(id));
    }
}
