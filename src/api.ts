import type {
  ChatMessageRepository, ChatRouteMode, ChatRouteResponse, ChatThread, FolderRecommendation,
  GraphData, HistoryItem, IngestResult, LibraryFolder, LibraryItem, Note, Paper, PaperChunk, PaperProcessingEnqueueResult,
  PaperDocument, PaperSummary, ProjectEntityEvidence, QaResponse, ResearchArtifact,
  ResearchCitation, ResearchProject, ResearchProjectAnalysis, ResearchProjectArtifact,
  ResearchProjectArtifactType, ResearchProjectBacklink, ResearchProjectCoverage,
  ResearchProjectItem, ResearchProjectItemInput, ResearchReportLibraryItem, ResearchRun,
  ResearchRunPaper, Stats, Subscription, User, WikiSearchResult,
} from "./types";

export const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

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

export async function fetchResearchRuns(): Promise<ResearchRun[]> {
  const data = await request<{ items: ResearchRun[] }>("/api/research/runs")
  return data.items
}

export async function fetchResearchRun(runId: string): Promise<ResearchRun> {
  return request<ResearchRun>(`/api/research/runs/${runId}`)
}

export async function fetchResearchArtifacts(runId: string): Promise<ResearchArtifact[]> {
  const data = await request<{ items: ResearchArtifact[] }>(`/api/research/runs/${runId}/artifacts`)
  return data.items
}

export async function fetchResearchRunPapers(runId: string): Promise<ResearchRunPaper[]> {
  const data = await request<{ items: ResearchRunPaper[] }>(`/api/research/runs/${runId}/papers`)
  return data.items
}

export async function fetchResearchCitations(runId: string): Promise<ResearchCitation[]> {
  const data = await request<{ items: ResearchCitation[] }>(`/api/research/runs/${runId}/citations`)
  return data.items
}

export async function fetchResearchCitationEvidence(runId: string, citationId: string): Promise<ResearchCitation> {
  return request<ResearchCitation>(`/api/research/runs/${runId}/citations/${citationId}/evidence`)
}

export async function fetchResearchReports(runId: string): Promise<ResearchArtifact[]> {
  const data = await request<{ items: ResearchArtifact[] }>(`/api/research/runs/${runId}/reports`)
  return data.items
}

export async function regenerateResearchReport(runId: string): Promise<ResearchRun> {
  return request<ResearchRun>(`/api/research/runs/${runId}/report-regeneration`, { method: "POST" })
}

export async function fetchResearchProjects(status?: "active" | "archived"): Promise<ResearchProject[]> {
  const suffix = status ? `?status=${status}` : ""
  const data = await request<{ items: ResearchProject[] }>(`/api/research/projects${suffix}`)
  return data.items
}

export async function createResearchProject(payload: { title: string; description?: string }): Promise<ResearchProject> {
  return request<ResearchProject>("/api/research/projects", { method: "POST", body: JSON.stringify(payload) })
}

export async function fetchResearchProject(projectId: string): Promise<ResearchProject> {
  return request<ResearchProject>(`/api/research/projects/${projectId}`)
}

export async function updateResearchProject(projectId: string, payload: { title?: string; description?: string }): Promise<ResearchProject> {
  return request<ResearchProject>(`/api/research/projects/${projectId}`, { method: "PATCH", body: JSON.stringify(payload) })
}

export async function deleteResearchProject(projectId: string): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(`/api/research/projects/${projectId}`, { method: "DELETE" })
}

export async function setResearchProjectArchived(projectId: string, archived: boolean): Promise<ResearchProject> {
  return request<ResearchProject>(`/api/research/projects/${projectId}/${archived ? "archive" : "restore"}`, { method: "POST" })
}

export async function fetchResearchProjectItems(projectId: string): Promise<ResearchProjectItem[]> {
  const data = await request<{ items: Array<Record<string, unknown>> }>(`/api/research/projects/${projectId}/items`)
  return data.items.map((item) => {
    const status = String(item.dependency_status ?? item.status ?? "inaccessible")
    const source = item.source && typeof item.source === "object" ? item.source as Record<string, unknown> : {}
    const content = source.content && typeof source.content === "object" ? source.content as Record<string, unknown> : {}
    return {
      ...item,
      project_id: String(item.project_id ?? projectId),
      dependency_status: status === "valid" || status === "current" ? "current" : status === "stale" ? "stale" : "inaccessible",
      title: status === "inaccessible" ? null : String(item.title ?? source.title ?? content.title ?? ""),
      subtitle: status === "inaccessible" ? null : String(item.subtitle ?? source.goal ?? source.source_id ?? content.topic ?? ""),
    } as ResearchProjectItem
  })
}

export async function addResearchProjectItem(projectId: string, payload: ResearchProjectItemInput): Promise<ResearchProjectItem> {
  return request<ResearchProjectItem>(`/api/research/projects/${projectId}/items`, { method: "POST", body: JSON.stringify(payload) })
}

export async function removeResearchProjectItem(projectId: string, itemId: string): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(`/api/research/projects/${projectId}/items/${itemId}`, { method: "DELETE" })
}

export async function reorderResearchProjectItems(projectId: string, itemIds: string[]): Promise<ResearchProjectItem[]> {
  const data = await request<{ items: ResearchProjectItem[] }>(`/api/research/projects/${projectId}/items/reorder`, {
    method: "POST", body: JSON.stringify({ item_ids: itemIds }),
  })
  return data.items
}

export async function fetchResearchProjectCoverage(projectId: string): Promise<ResearchProjectCoverage> {
  return request<ResearchProjectCoverage>(`/api/research/projects/${projectId}/coverage`)
}

export async function fetchResearchProjectAnalysis(projectId: string): Promise<ResearchProjectAnalysis> {
  return request<ResearchProjectAnalysis>(`/api/research/projects/${projectId}/analysis`)
}

export async function startResearchProjectAnalysis(projectId: string): Promise<ResearchProjectAnalysis> {
  return request<ResearchProjectAnalysis>(`/api/research/projects/${projectId}/analysis`, { method: "POST" })
}

export async function controlResearchProjectAnalysis(projectId: string, action: "pause" | "resume" | "cancel" | "retry"): Promise<ResearchProjectAnalysis> {
  return request<ResearchProjectAnalysis>(`/api/research/projects/${projectId}/analysis/${action}`, { method: "POST" })
}

const projectArtifactView: Partial<Record<ResearchProjectArtifactType, string>> = {
  topic_clusters: "topic-clusters",
  research_timeline: "timeline",
  research_graph: "graph",
}

export async function fetchResearchProjectArtifact<T extends object>(
  projectId: string,
  artifactType: ResearchProjectArtifactType,
  version?: number,
): Promise<ResearchProjectArtifact<T>> {
  const view = projectArtifactView[artifactType]
  if (!view) throw new Error("project artifact view is not exposed")
  const suffix = version == null ? "" : `?version=${version}`
  return request<ResearchProjectArtifact<T>>(`/api/research/projects/${projectId}/artifacts/${view}${suffix}`)
}

export async function fetchResearchProjectArtifactVersions(projectId: string, artifactType: ResearchProjectArtifactType): Promise<ResearchProjectArtifact[]> {
  const view = projectArtifactView[artifactType]
  if (!view) return []
  const data = await request<{ items: ResearchProjectArtifact[] }>(`/api/research/projects/${projectId}/artifacts/${view}/versions`)
  return data.items
}

export async function fetchProjectEntityEvidence(
  projectId: string,
  artifactVersion: number,
  entityKind: ProjectEntityEvidence["entity_kind"],
  entityId: string,
): Promise<ProjectEntityEvidence> {
  const raw = await request<{ entity_id: string; entity_kind: "node" | "edge"; dependency_status: string; citations: Array<Record<string, unknown>> }>(`/api/research/projects/${projectId}/entities/${entityKind}/${encodeURIComponent(entityId)}/evidence?artifact_version=${artifactVersion}`)
  return {
    entity_id: raw.entity_id,
    entity_kind: entityKind,
    dependency_status: raw.dependency_status === "current" ? "current" : raw.dependency_status === "stale" ? "stale" : "inaccessible",
    citations: raw.citations.map((item, index) => ({
      citation_id: String(item.citation_id ?? `${entityId}-${index}`), citation_label: `引用 ${index + 1}`,
      status: String(item.status ?? "invalid") as ResearchCitation["status"],
      paper_id: typeof item.paper_id === "number" ? item.paper_id : null,
      paper_title: typeof item.paper_title === "string" ? item.paper_title : null,
      heading: typeof item.heading === "string" ? item.heading : null,
      excerpt: typeof item.excerpt === "string" ? item.excerpt : null,
      chunk_id: typeof item.chunk_id === "number" ? item.chunk_id : null,
      char_start: typeof item.char_start === "number" ? item.char_start : null,
      char_end: typeof item.char_end === "number" ? item.char_end : null,
    })),
  }
}

export async function fetchResearchProjectBacklinks(item: ResearchProjectItemInput): Promise<ResearchProjectBacklink[]> {
  const params = new URLSearchParams({ item_type: item.item_type })
  if (item.item_type === "run") params.set("run_id", item.run_id)
  if (item.item_type === "paper") params.set("paper_id", String(item.paper_id))
  if (item.item_type === "research_report") {
    params.set("artifact_id", item.artifact_id)
    params.set("artifact_version", String(item.artifact_version))
  }
  const data = await request<{ items: ResearchProjectBacklink[] }>(`/api/research/projects/backlinks?${params}`)
  return data.items
}

export async function fetchResearchReportLibrary(): Promise<ResearchReportLibraryItem[]> {
  const runs = (await fetchResearchRuns()).filter((run) => run.mode === "topic")
  const groups = await Promise.all(runs.map(async (run) => {
    try {
      const reports = await fetchResearchReports(run.id)
      return reports.map((artifact) => {
        const content = artifact.content as Partial<{ title: string; topic: string }>
        return {
          artifact_id: artifact.id, artifact_version: artifact.version, run_id: run.id, run_title: run.title,
          title: content.title ?? "未命名报告", topic: content.topic ?? run.goal,
          status: artifact.status === "stale" ? "stale" : "completed", is_current: artifact.is_current,
          created_at: artifact.created_at, updated_at: artifact.updated_at,
        } satisfies ResearchReportLibraryItem
      })
    } catch { return [] }
  }))
  return groups.flat().sort((a, b) => b.updated_at.localeCompare(a.updated_at))
}

export async function createResearchRun(payload: {
  title: string
  goal: string
  thread_id?: string
}): Promise<ResearchRun> {
  return request<ResearchRun>("/api/research/runs", {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export async function controlResearchRun(
  runId: string,
  action: "pause" | "resume" | "cancel" | "retry",
): Promise<ResearchRun> {
  return request<ResearchRun>(`/api/research/runs/${runId}/${action}`, { method: "POST" })
}

export async function resolveResearchDecision(decisionId: string, optionId: string): Promise<ResearchRun> {
  return request<ResearchRun>(`/api/research/decisions/${decisionId}/resolve`, {
    method: "POST",
    body: JSON.stringify({ option_id: optionId }),
  })
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

export async function parsePaperDocument(id: number): Promise<PaperProcessingEnqueueResult> {
  return request<PaperProcessingEnqueueResult>(`/api/papers/${id}/document/parse`, { method: "POST" });
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

export async function routeChatMessage(payload: {
  thread_id: string
  mode: ChatRouteMode
  user_message: {
    id: string
    parent_id?: string | null
    source_message_id?: string | null
    content: string
  }
  assistant_message_id: string
  message_token_limit?: number
}): Promise<ChatRouteResponse> {
  return request<ChatRouteResponse>("/api/chat/route", {
    method: "POST",
    body: JSON.stringify(payload),
  })
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

export async function uploadPaper(
  file: File,
  details: { title?: string; authors?: string; year?: number; visibility?: "private" | "public" } = {},
): Promise<Paper> {
  const body = new FormData()
  body.set("file", file)
  if (details.title) body.set("title", details.title)
  if (details.authors) body.set("authors", details.authors)
  if (details.year) body.set("year", String(details.year))
  body.set("visibility", details.visibility ?? "private")
  return request<Paper>("/api/papers/upload", { method: "POST", body })
}

export async function updateUploadVisibility(
  paperId: number,
  visibility: "private" | "public",
): Promise<Paper> {
  return request<Paper>(`/api/papers/${paperId}/visibility`, {
    method: "PATCH",
    body: JSON.stringify({ visibility }),
  })
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
