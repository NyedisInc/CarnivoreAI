export function useThemeKey(): { readonly value: string | null } {
    const read = (): string | null => (typeof document === 'undefined' ? null : (document.documentElement.dataset['theme'] ?? null));
    let value = $state<string | null>(read());
    $effect(() => {
        if (typeof MutationObserver === 'undefined') return;
        const observer = new MutationObserver(() => (value = read()));
        observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
        return () => observer.disconnect();
    });
    return {
        get value() {
            return value;
        },
    };
}
