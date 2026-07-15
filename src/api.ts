import type { ChatMessageRepository, ChatThread, FolderRecommendation, GraphData, HistoryItem, IngestResult, LibraryFolder, LibraryItem, Note, Paper, PaperChunk, PaperDocument, PaperSummary, QaResponse, Stats, Subscription, User, WikiSearchResult } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers ?? {})
  if (!(options?.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json")
  }
  const response = await fetch(`${API_BASE}${path}`, { ...options, credentials: "include", headers });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function fetchCurrentUser(): Promise<User> {
  return request<User>("/api/auth/me");
}

export async function login(username: string, password: string): Promise<User> {
  return request<User>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export async function register(username: string, password: string): Promise<User> {
  return request<User>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export async function logout(): Promise<void> {
  const response = await fetch(`${API_BASE}/api/auth/logout`, {
    method: "POST",
    credentials: "include",
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
}

export async function fetchStats(): Promise<Stats> {
  return request<Stats>("/api/stats");
}

export async function fetchPapers(params: Record<string, string | boolean | number | undefined> = {}): Promise<Paper[]> {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "" && value !== false) {
      search.set(key, String(value));
    }
  });
  const data = await request<{ items: Paper[] }>(`/api/papers?${search.toString()}`);
  return data.items;
}

export async function fetchPaperDetail(id: number): Promise<Paper> {
  return request<Paper>(`/api/papers/${id}`);
}

export async function fetchPaperChunks(id: number): Promise<PaperChunk[]> {
  const data = await request<{ items: PaperChunk[] }>(`/api/papers/${id}/chunks?limit=200`)
  return data.items
}

export async function processPaper(id: number): Promise<Paper> {
  const data = await request<{ paper: Paper }>(`/api/papers/${id}/process`, { method: "POST" });
  return data.paper;
}

export async function parsePaperDocument(id: number): Promise<PaperDocument> {
  return request<PaperDocument>(`/api/papers/${id}/document/parse`, { method: "POST" });
}

export async function generatePaperSummary(id: number): Promise<PaperSummary> {
  return request<PaperSummary>(`/api/papers/${id}/summaries`, { method: "POST" });
}

export async function fetchPaperChatThreads(paperId: number): Promise<ChatThread[]> {
  const data = await request<{ items: ChatThread[] }>(`/api/papers/${paperId}/chat/threads`);
  return data.items;
}

export async function createPaperChatThread(paperId: number, title = "新对话"): Promise<ChatThread> {
  return request<ChatThread>(`/api/papers/${paperId}/chat/threads`, {
    method: "POST",
    body: JSON.stringify({ title }),
  });
}

export async function fetchGeneralChatThreads(): Promise<ChatThread[]> {
  const data = await request<{ items: ChatThread[] }>("/api/chat/threads")
  return data.items
}

export async function createGeneralChatThread(title = "新对话"): Promise<ChatThread> {
  return request<ChatThread>("/api/chat/threads", {
    method: "POST",
    body: JSON.stringify({ title }),
  })
}

export async function fetchChatMessages(threadId: string): Promise<ChatMessageRepository> {
  return request<ChatMessageRepository>(`/api/chat/threads/${threadId}/messages`);
}

export async function updateChatThreadHead(threadId: string, headId?: string): Promise<ChatThread> {
  return request<ChatThread>(`/api/chat/threads/${threadId}/head`, {
    method: "PATCH",
    body: JSON.stringify({ head_id: headId ?? null }),
  });
}

export async function ingestArxiv(payload: { categories: string[]; keywords: string[]; max_results: number }) {
  return request<IngestResult>("/api/ingest/arxiv", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function ingestSource(
  source: "usenix" | "sigops",
  payload: { venue: string; year: number; keywords?: string[]; max_results: number; proceedings_url?: string }
) {
  return request<IngestResult>(`/api/ingest/${source}`, {
    method: "POST",
    body: JSON.stringify({ categories: [], keywords: payload.keywords ?? [], ...payload })
  });
}

export async function uploadPaper(file: File, details: { title?: string; authors?: string; year?: number } = {}): Promise<Paper> {
  const body = new FormData()
  body.set("file", file)
  if (details.title) body.set("title", details.title)
  if (details.authors) body.set("authors", details.authors)
  if (details.year) body.set("year", String(details.year))
  return request<Paper>("/api/papers/upload", { method: "POST", body })
}

export async function searchWiki(q: string): Promise<WikiSearchResult[]> {
  const data = await request<{ items: WikiSearchResult[] }>(`/api/wiki/search?q=${encodeURIComponent(q)}&limit=8`);
  return data.items;
}

export async function askQuestion(question: string, paperIds: number[] = [], mode: "agentic" | "classic" = "agentic"): Promise<QaResponse> {
  return request<QaResponse>("/api/qa", {
    method: "POST",
    body: JSON.stringify({ question, paper_ids: paperIds, mode })
  });
}

export async function fetchGraph(topic = ""): Promise<GraphData> {
  return request<GraphData>(`/api/graph?topic=${encodeURIComponent(topic)}&limit=42`);
}

export async function toggleFavorite(paperId: number, favorite: boolean): Promise<Paper> {
  return request<Paper>("/api/library/favorites", {
    method: "POST",
    body: JSON.stringify({ paper_id: paperId, favorite })
  });
}

export async function addNote(paperId: number, note: string, comment = ""): Promise<Note> {
  return request<Note>("/api/notes", {
    method: "POST",
    body: JSON.stringify({ paper_id: paperId, note, comment })
  });
}

export async function fetchHistory(): Promise<HistoryItem[]> {
  const data = await request<{ items: HistoryItem[] }>("/api/history?limit=30");
  return data.items;
}

export async function fetchSubscriptions(): Promise<Subscription[]> {
  const data = await request<{ items: Subscription[] }>("/api/subscriptions");
  return data.items;
}

export async function addSubscription(topic: string): Promise<Subscription> {
  return request<Subscription>("/api/subscriptions", {
    method: "POST",
    body: JSON.stringify({ topic })
  });
}

export async function fetchLibraryFolders(): Promise<LibraryFolder[]> {
  const data = await request<{ items: LibraryFolder[] }>("/api/library/folders");
  return data.items;
}

export async function createLibraryFolder(payload: { name: string; parent_id?: number; description?: string }): Promise<LibraryFolder> {
  return request<LibraryFolder>("/api/library/folders", { method: "POST", body: JSON.stringify(payload) });
}

export async function deleteLibraryFolder(folderId: number): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(`/api/library/folders/${folderId}`, { method: "DELETE" });
}

export async function fetchLibraryItems(folderId?: number): Promise<LibraryItem[]> {
  const suffix = folderId ? `?folder_id=${folderId}` : "";
  const data = await request<{ items: LibraryItem[] }>(`/api/library/items${suffix}`);
  return data.items;
}

export async function moveLibraryItem(itemId: number, folderId: number): Promise<LibraryItem> {
  return request<LibraryItem>(`/api/library/items/${itemId}/move`, {
    method: "POST",
    body: JSON.stringify({ folder_id: folderId })
  });
}

export async function recommendLibraryFolder(itemId: number): Promise<FolderRecommendation> {
  return request<FolderRecommendation>(`/api/library/items/${itemId}/recommend-folder`, { method: "POST" });
}
