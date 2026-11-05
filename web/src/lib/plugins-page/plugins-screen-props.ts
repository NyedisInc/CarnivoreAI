import type { ManagerAdapter } from '../manager-frame/types';
import type { Translate } from '../sessions/types';
import type { CatalogPlugins } from './catalog-plugins.svelte';
import type { GrantOptions } from './cplug-grant';
import type { ActivityRow, CplugSheet } from './cplugs-adapter';
import type { PurgePrice } from './plugin-pane';
import type { PageScope } from './plugin-scope';

export interface PluginsScreenProps {
    adapter?: ManagerAdapter;
    t?: Translate;
    embedded?: boolean;
    focusId?: string | null;
    focusTab?: string | null;
    onSelect?: (cplugId: string, tab: string) => void;
    onChanged?: () => void;
    storeOnly?: boolean;
    scope?: PageScope;
    developerMode?: boolean;
    grant?: (cplugId: string, ticks: string[], options: GrantOptions) => Promise<unknown>;
    loadSheet?: (cplugId: string) => Promise<CplugSheet>;
    loadActivity?: (cplugId: string) => Promise<ActivityRow[]>;
    purge?: (cplugId: string, confirmToken?: string) => Promise<PurgePrice>;
    catalog?: CatalogPlugins | null;
}
