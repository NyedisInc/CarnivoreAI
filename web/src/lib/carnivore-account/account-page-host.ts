
export interface AccountPageHost {
    readNews(): Promise<boolean | null>;
    setNews(news: boolean): Promise<boolean>;
}

interface Api {
    getPublishAccount(): Promise<{ news_opt_in?: boolean | null }>;
    setCatalogNews(news: boolean): Promise<{ news_opt_in?: boolean }>;
}

export function browserAccountPageHost(): AccountPageHost {
    const api = (): Api => (globalThis as unknown as { API: Api }).API;
    return {
        readNews: async () => {
            const account = await api().getPublishAccount();
            return typeof account?.news_opt_in === 'boolean' ? account.news_opt_in : null;
        },
        setNews: async (news) => {
            const saved = await api().setCatalogNews(news);
            return saved?.news_opt_in === true;
        },
    };
}
