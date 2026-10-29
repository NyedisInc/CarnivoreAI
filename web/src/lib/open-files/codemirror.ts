
export interface CodeEditor {
    getValue(): string;
    setContent(content: string, path: string, readOnly: boolean): void;
    setReadOnly(readOnly: boolean): void;
    focus(): void;
    destroy(): void;
}

export interface CodeMirrorBundle {
    createEditor(
        host: HTMLElement, content: string, path: string, readOnly: boolean, onChange: (value: string) => void,
    ): CodeEditor;
}

export const CONFIG_EDITOR_FAMILY = 'config-editor';

interface EditorGlobals {
    CodeMirrorBundle?: CodeMirrorBundle;
    ModuleLoader?: { loadFamily?: (name: string, urls: string[]) => Promise<unknown> };
    ModuleFamilies?: { CONFIG_EDITOR?: string[] };
}

export class EditorUnavailableError extends Error {
    constructor(message: string) {
        super(message);
        this.name = 'EditorUnavailableError';
    }
}

export async function loadCodeMirror(g: EditorGlobals = globalThis as unknown as EditorGlobals): Promise<CodeMirrorBundle> {
    if (g.CodeMirrorBundle) return g.CodeMirrorBundle;
    const load = g.ModuleLoader?.loadFamily;
    if (typeof load !== 'function') throw new EditorUnavailableError('the module loader is not on this page');
    await load(CONFIG_EDITOR_FAMILY, g.ModuleFamilies?.CONFIG_EDITOR ?? []);
    if (!g.CodeMirrorBundle) throw new EditorUnavailableError('the editor family loaded without the editor');
    return g.CodeMirrorBundle;
}
