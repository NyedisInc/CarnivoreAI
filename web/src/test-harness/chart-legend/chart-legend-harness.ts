import '../../app.css';
import '../../opscenter/app.css';
import { mount } from 'svelte';
import ChartLegend from '../../opscenter/cells/analytics/ChartLegend.svelte';

const NAMES = ['opus', 'sonnet', 'haiku', 'codex-gpt-5', 'local-llama', 'gemini'];
const COLORS = ['var(--oc-cyan)', 'var(--oc-orange)', 'var(--oc-green)', 'var(--oc-pink)', 'var(--oc-coral)', 'var(--oc-text-secondary)'];
const items = NAMES.map((name, i) => ({ name, color: COLORS[i]!, on: i !== 2, id: `s${i}` }));

function legend(key: string, wrap: boolean): void {
    const target = document.querySelector(`[data-rh="${key}"]`);
    if (target) mount(ChartLegend, { target, props: { items, onToggle: () => {}, wrap } });
}

legend('single', false);
legend('wrap', true);
document.documentElement.dataset.rhReady = '1';
