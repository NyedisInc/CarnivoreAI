import { EditorState, Compartment } from '@codemirror/state';
import {
    EditorView, keymap, lineNumbers, highlightActiveLine,
    highlightActiveLineGutter, drawSelection,
} from '@codemirror/view';
import {
    defaultKeymap, history, historyKeymap, indentWithTab,
} from '@codemirror/commands';
import {
    indentOnInput, bracketMatching, syntaxHighlighting, defaultHighlightStyle,
    foldGutter, foldKeymap,
} from '@codemirror/language';
import { searchKeymap, highlightSelectionMatches } from '@codemirror/search';
import { markdown } from '@codemirror/lang-markdown';
import { json } from '@codemirror/lang-json';
import { python } from '@codemirror/lang-python';
import { javascript } from '@codemirror/lang-javascript';
import { StreamLanguage } from '@codemirror/language';
import { shell } from '@codemirror/legacy-modes/mode/shell';

function languageForPath(path) {
    const ext = String(path || '').toLowerCase().split('.').pop();
    switch (ext) {
        case 'md':
        case 'markdown':
            return markdown();
        case 'json':
            return json();
        case 'py':
            return python();
        case 'js':
        case 'cjs':
        case 'mjs':
            return javascript();
        case 'sh':
        case 'bash':
        case 'zsh':
            return StreamLanguage.define(shell);
        default:
            return null;
    }
}

function buildState(content, path, readOnly, onChange) {
    const languageExt = languageForPath(path);
    const extensions = [
        lineNumbers(),
        highlightActiveLineGutter(),
        highlightActiveLine(),
        drawSelection(),
        history(),
        indentOnInput(),
        bracketMatching(),
        foldGutter(),
        highlightSelectionMatches(),
        syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
        keymap.of([
            ...defaultKeymap,
            ...historyKeymap,
            ...searchKeymap,
            ...foldKeymap,
            indentWithTab,
        ]),
        EditorView.lineWrapping,
        EditorState.readOnly.of(!!readOnly),
        EditorView.updateListener.of((update) => {
            if (update.docChanged && typeof onChange === 'function') {
                onChange(update.state.doc.toString());
            }
        }),
    ];
    if (languageExt) extensions.push(languageExt);
    return EditorState.create({ doc: content || '', extensions });
}

function createEditor(container, content, path, readOnly, onChange) {
    const state = buildState(content, path, readOnly, onChange);
    const view = new EditorView({ state, parent: container });

    return {
        getValue() {
            return view.state.doc.toString();
        },
        setContent(newContent, newPath, newReadOnly) {
            view.setState(buildState(newContent, newPath, newReadOnly, onChange));
        },
        setReadOnly(newReadOnly) {
            view.setState(buildState(view.state.doc.toString(), path, newReadOnly, onChange));
        },
        focus() {
            view.focus();
        },
        destroy() {
            view.destroy();
        },
    };
}

window.CodeMirrorBundle = { createEditor, languageForPath };
