import { mount } from 'svelte';

import App from './App.svelte';
import './admin.css';

const target = document.getElementById('admin-root');
if (target) {
    mount(App, { target });
}
