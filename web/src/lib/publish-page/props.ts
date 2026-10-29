import type { Translate } from '../sessions/types';
import type { PageActions } from './actions';
import type { PageStore } from './page-store.svelte';

export interface PageProps {
    store: PageStore;
    actions: PageActions;
    t: Translate;
}
