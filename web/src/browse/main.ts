import './browse.css';
import { mountPanel } from '../lib/mount';
import { t } from '../lib/i18n/index.svelte';
import CatalogScreen from '../lib/catalog/CatalogScreen.svelte';
import { staticCatalogHost } from './static-host';

const screen = mountPanel('browse-root', CatalogScreen as never, {
    host: staticCatalogHost(),
    title: t('warez.title'),
    t,
    bands: true,
    readonly: true,
}) as { show?: (options?: Record<string, unknown>) => void } | null;
screen?.show?.({});
