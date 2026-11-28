import { getContext, setContext } from 'svelte';

export type FieldValue = string | boolean;
export type FieldValidator = () => string | null;

export interface FormContext {
    registerField(name: string, initial: FieldValue, validate: FieldValidator): () => void;
    setField(name: string, value: FieldValue): void;
    validateAll(): boolean;
    snapshot(): Record<string, FieldValue>;
}

const FORM_KEY = Symbol('cplug-ui-form');

export function provideForm(): FormContext {
    const values = new Map<string, FieldValue>();
    const validators = new Map<string, FieldValidator>();
    const ctx: FormContext = {
        registerField(name, initial, validate) {
            if (!values.has(name)) values.set(name, initial);
            validators.set(name, validate);
            return () => {
                values.delete(name);
                validators.delete(name);
            };
        },
        setField(name, value) {
            values.set(name, value);
        },
        validateAll() {
            let ok = true;
            for (const validate of validators.values()) {
                if (validate() !== null) ok = false;
            }
            return ok;
        },
        snapshot() {
            const out: Record<string, FieldValue> = {};
            for (const [k, v] of values.entries()) out[k] = v;
            return out;
        },
    };
    setContext(FORM_KEY, ctx);
    return ctx;
}

export function useForm(): FormContext | null {
    return getContext<FormContext | undefined>(FORM_KEY) ?? null;
}
