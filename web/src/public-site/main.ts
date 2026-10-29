import { hydrate } from 'svelte';
import Page from './Page.svelte';

const target = document.getElementById('site-root');
if (!target) {
    throw new Error('Missing #site-root for public site hydration');
}

hydrate(Page, { target });
