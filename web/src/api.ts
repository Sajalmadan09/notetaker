export type Turn = { start: number; end: number; speaker: number; text: string };
export type ActionItem = { text: string; owner: string; done: boolean };
export type Summary = {
  title: string; overview: string; action_items: ActionItem[]; decisions: string[];
  chapters: { title: string; start: number }[]; provider: string; model: string; ts: string;
};
export type Row = {
  id: string; ts: string; title?: string; lang: string; engine?: string; duration_s: number;
  turn_count: number; preview: string; audio?: string; source?: string; verdict?: string;
};
export type Recording = Row & {
  mode?: string; turns: Turn[]; names?: Record<string, string>; summary?: Summary;
  insert_path?: string; asr_ms?: number; raw_text?: string; cleanup_ms?: number; app?: string;
};
export type Provider = {
  label: string; kind: "anthropic" | "openai"; local: boolean; needs_key: boolean;
  base_url: string; model: string; has_key: boolean;
};
export type Connector = {
  id: string; label: string; about: string; server: string; secrets: Record<string, string>;
  fields: Record<string, string>; values: Record<string, string>; has_secret: Record<string, boolean>;
  configured: boolean; needs_node: boolean;
};
export type CalEvent = { id: string; title: string; start: string; end: string; attendees: string[]; meet: string };
export type Dictation = { cleanup: boolean; match_app: boolean; dictionary: string[] };
export type LLMSettings = { provider: string; summary_language: string; dictation: Dictation; providers: Record<string, Provider> };

async function call<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init ?? {};
  const r = await fetch(path, json === undefined ? rest : {
    ...rest, body: JSON.stringify(json), headers: { "Content-Type": "application/json" },
  });
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try { msg = (await r.json()).detail ?? msg; } catch { /* not JSON */ }
    throw new Error(msg);
  }
  return r.json();
}

export const api = {
  list: () => call<Row[]>("/api/history"),
  get: (id: string) => call<Recording>(`/api/history/${id}`),
  patch: (id: string, body: Partial<{ title: string; names: Record<string, string>; summary: Summary }>) =>
    call<Recording>(`/api/history/${id}`, { method: "PATCH", json: body }),
  remove: (id: string) => call<unknown>(`/api/history/${id}`, { method: "DELETE" }),
  summarize: (id: string) => call<Recording>(`/api/history/${id}/summarize`, { method: "POST" }),
  ask: (id: string, question: string, prior: { role: string; content: string }[]) =>
    call<{ answer: string }>(`/api/history/${id}/ask`, { method: "POST", json: { question, prior } }),
  llm: () => call<LLMSettings>("/api/llm/settings"),
  saveLlm: (body: unknown) => call<LLMSettings>("/api/llm/settings", { method: "PUT", json: body }),
  models: (provider: string) => call<string[]>(`/api/llm/models?provider=${provider}`),
  tryCleanup: (text: string, app: string) =>
    call<{ text: string; raw: string; cleaned: boolean; ms: number; error: string }>("/api/dictation/cleanup", { method: "POST", json: { text, app } }),
  health: () => call<{ torch: boolean }>("/api/health"),
  connectors: () => call<{ connectors: Connector[]; slack_manifest: unknown }>("/api/connectors"),
  saveConnector: (id: string, body: { values?: Record<string, string>; secrets?: Record<string, string> }) =>
    call<Connector>(`/api/connectors/${id}`, { method: "PUT", json: body }),
  testConnector: (id: string) => call<{ tools: string[] }>(`/api/connectors/${id}/test`, { method: "POST" }),
  disconnectConnector: (id: string) => call<Connector>(`/api/connectors/${id}/disconnect`, { method: "POST" }),
  googleConnect: (id: string) => call<{ url: string; redirect_uri: string }>(`/api/connectors/${id}/connect`, { method: "POST" }),
  gmailPreview: (rid: string) => call<{ subject: string; body: string; to: string[] }>(`/api/history/${rid}/share/gmail`),
  upcoming: () => call<CalEvent[]>("/api/calendar/upcoming"),
  gmailDraft: (rid: string, to: string[], subject: string, body: string) =>
    call<{ draft_id: string }>(`/api/history/${rid}/share/gmail`, { method: "POST", json: { to, subject, body } }),
  slackChannels: () => call<{ id: string; name: string }[]>("/api/connectors/slack/channels"),
  slackPreview: (rid: string) => call<{ text: string }>(`/api/history/${rid}/share/slack`),
  slackPost: (rid: string, channel_id: string, text: string) =>
    call<{ result: string }>(`/api/history/${rid}/share/slack`, { method: "POST", json: { channel_id, text } }),
  languages: () => call<string[]>("/api/languages"),
  createJob: (wav: Blob, o: Record<string, string>) => {
    const fd = new FormData(); fd.append("file", wav, "audio.wav");
    for (const [k, v] of Object.entries(o)) fd.append(k, v);
    return call<{ job_id: string }>("/api/jobs", { method: "POST", body: fd });
  },
  job: (id: string) => call<{ status: string; stage: string; progress: number; error?: string }>(`/api/jobs/${id}`),
  quick: (wav: Blob, lang: string) => {
    const fd = new FormData(); fd.append("file", wav, "chunk.wav"); fd.append("lang", lang);
    return call<{ text: string; lang: string }>("/api/quick", { method: "POST", body: fd });
  },
};

export const audioUrl = (id: string) => `/api/history/${id}/audio`;
export const exportUrl = (id: string, fmt: string) => `/api/history/${id}/export?fmt=${fmt}`;
