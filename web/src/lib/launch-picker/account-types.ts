
export interface AccountChoice {
    id: string;
    name: string;
    color?: string | null;
    is_current?: boolean;
}

export interface RestartAccounts {
    options: AccountChoice[];
    selected_id?: string | null;
    current_id?: string | null;
    active_id?: string | null;
    pinned?: boolean;
}
