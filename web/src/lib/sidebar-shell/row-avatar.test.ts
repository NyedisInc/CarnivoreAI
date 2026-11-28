/** @vitest-environment jsdom */
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
import RowAvatar from './RowAvatar.svelte';

const mounted: Array<{ app: ReturnType<typeof mount>; el: HTMLElement }> = [];
afterEach(() => {
    for (const m of mounted) {
        unmount(m.app);
        m.el.remove();
    }
    mounted.length = 0;
});

function render(props: Record<string, unknown>): HTMLElement {
    const el = document.body.appendChild(document.createElement('div'));
    const app = mount(RowAvatar, { target: el, props: props as never });
    flushSync();
    mounted.push({ app, el });
    return el;
}

const provider = {
    attrs: {
        class: 'session-sidebar-row-provider',
        'data-grip-session': 'claude_demo',
        'data-agent-family': 'claude',
        role: 'img',
        'aria-label': 'claude',
        title: 'claude',
    },
    svg: '<svg data-testid="real-claude-logo"></svg>',
};

describe('RowAvatar (#3387)', () => {
    it('renders the real provider logo directly when no model robot is present and dims when asleep', () => {
        const el = render({ provider, model: null, asleep: true, size: 'sm' });
        const slot = el.querySelector('.sb-avatar') as HTMLElement;
        expect(slot.dataset.gripSession).toBe('claude_demo');
        expect(slot.dataset.agentFamily).toBe('claude');
        expect(slot.classList.contains('sb-avatar--asleep')).toBe(true);
        expect(slot.querySelector('[data-testid="real-claude-logo"]')).not.toBeNull();
        expect(slot.querySelector('.sb-avatar__badge')).toBeNull();
    });

    it('merges ModelMark face + real AI provider corner badge + lead star when live', () => {
        const model = {
            attrs: { class: 'session-sidebar-row-model', 'data-tier': '5', role: 'img', 'aria-label': 'opus' },
            svg: '<rect data-testid="robot-face"/>',
            spark: true,
            sheen: false,
        };
        const el = render({
            provider,
            model,
            leadHtml: '<span class="session-sidebar-row-provider__lead" data-testid="lead-star"></span>',
            asleep: false,
            size: 'md',
        });
        const slot = el.querySelector('.sb-avatar') as HTMLElement;
        expect(slot.dataset.avatarMerged).toBe('1');
        expect(slot.classList.contains('sb-avatar--md')).toBe(true);
        expect(slot.querySelector('.sb-avatar__face [data-testid="robot-face"]')).not.toBeNull();
        expect(slot.querySelector('.sb-avatar__badge [data-testid="real-claude-logo"]')).not.toBeNull();
        expect(slot.querySelector(':scope > [data-testid="lead-star"]')).not.toBeNull();
        expect(slot.querySelector('.session-sidebar-row-model__spark')).not.toBeNull();
    });
});
