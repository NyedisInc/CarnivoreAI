
const IGNORE_ATTRIBUTES: Readonly<Record<string, string>> = {
    autocomplete: 'off',
    autocapitalize: 'off',
    autocorrect: 'off',
    spellcheck: 'false',
    'data-1p-ignore': 'true',
    'data-lpignore': 'true',
    'data-bwignore': 'true',
    'data-form-type': 'other',
};

export function maskingSupported(): boolean {
    return typeof CSS !== 'undefined' && typeof CSS.supports === 'function' && CSS.supports('-webkit-text-security', 'disc');
}

export function secretField(node: HTMLInputElement, enabled: boolean = true): void {
    if (!enabled) return;
    for (const [name, value] of Object.entries(IGNORE_ATTRIBUTES)) node.setAttribute(name, value);
    node.classList.add('oc-secret');
    node.type = maskingSupported() ? 'text' : 'password';
}
