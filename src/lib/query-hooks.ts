import { useEffect } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  addNote,
  addSubscription,
  askQuestion,
  fetchGraph,
  fetchHistory,
  fetchLibraryFolders,
  fetchLibraryItems,
  fetchPaperDetail,
  fetchPaperChunks,
  fetchPapers,
  fetchStats,
  fetchSubscriptions,
  createLibraryFolder,
  deleteLibraryFolder,
  ingestArxiv,
  ingestSource,
  processPaper,
  parsePaperDocument,
  generatePaperSummary,
  moveLibraryItem,
  recommendLibraryFolder,
  searchWiki,
  toggleFavorite,
  uploadPaper,
  fetchCurrentUser,
  fetchResearchRun,
  fetchResearchRuns,
  fetchResearchArtifacts,
  fetchResearchRunPapers,
  fetchResearchCitations,
  fetchResearchCitationEvidence,
  fetchResearchReports,
  regenerateResearchReport,
  createResearchRun,
  controlResearchRun,
  resolveResearchDecision,
  fetchGeneralChatThreads,
  createGeneralChatThread,
  updateChatThreadTitle,
  updateChatThreadWorkspace,
  addResearchProjectItem,
  controlResearchProjectAnalysis,
  createResearchProject,
  deleteResearchProject,
  fetchProjectEntityEvidence,
  fetchResearchProject,
  fetchResearchProjectAnalysis,
  fetchResearchProjectArtifact,
  fetchResearchProjectArtifactVersions,
  fetchResearchProjectBacklinks,
  fetchResearchProjectCoverage,
  fetchResearchProjectItems,
  fetchResearchProjects,
  fetchResearchReportLibrary,
  removeResearchProjectItem,
  reorderResearchProjectItems,
  setResearchProjectArchived,
  startResearchProjectAnalysis,
  updateResearchProject,
  fetchWorkspaces,
  createWorkspace,
  updateWorkspace,
  deleteWorkspace,
} from "@/api"
import type {
  ProjectEntityEvidence, ResearchProjectArtifactType, ResearchProjectItemInput, ResearchRun,
} from "@/types"

export type PaperFilters = {
  q?: string
  category?: string
  concept?: string
  favorite?: boolean
  limit?: number
}

export type GraphFilters = {
  topic?: string
}

export type RouteHandle = {
  title: string
  navLabel?: string
}

export const queryKeys = {
  currentUser: ["current-user"] as const,
  stats: ["stats"] as const,
  papers: (filters: PaperFilters = {}) => ["papers", filters] as const,
  paper: (id: number) => ["paper", id] as const,
  paperChunks: (id: number) => ["paper-chunks", id] as const,
  wikiSearch: (q: string) => ["wiki-search", q] as const,
  qa: ["qa"] as const,
  graph: (filters: GraphFilters = {}) => ["graph", filters] as const,
  history: ["history"] as const,
  subscriptions: ["subscriptions"] as const,
  libraryFolders: ["library-folders"] as const,
  libraryItems: (folderId?: number) => ["library-items", folderId ?? "all"] as const,
  researchRuns: ["research-runs"] as const,
  researchRun: (id: string) => ["research-run", id] as const,
  researchArtifacts: (id: string) => ["research-artifacts", id] as const,
  researchRunPapers: (id: string) => ["research-run-papers", id] as const,
  researchProjects: (status?: "active" | "archived") => ["research-projects", status ?? "all"] as const,
  researchProject: (id: string) => ["research-project", id] as const,
  researchProjectItems: (id: string) => ["research-project", id, "items"] as const,
  researchProjectCoverage: (id: string) => ["research-project", id, "coverage"] as const,
  researchProjectAnalysis: (id: string) => ["research-project", id, "analysis"] as const,
  researchProjectArtifact: (id: string, type: ResearchProjectArtifactType, version?: number) => ["research-project", id, "artifact", type, version ?? "current"] as const,
  researchProjectArtifactVersions: (id: string, type: ResearchProjectArtifactType) => ["research-project", id, "artifact-versions", type] as const,
  researchProjectBacklinks: (item: ResearchProjectItemInput) => ["research-project-backlinks", item] as const,
  researchReportLibrary: ["research-report-library"] as const,
  chatThreads: ["chat-threads"] as const,
  workspaces: ["workspaces"] as const,
}

function invalidateResearchProject(queryClient: ReturnType<typeof useQueryClient>, projectId: string) {
  void queryClient.invalidateQueries({ queryKey: queryKeys.researchProject(projectId) })
  void queryClient.invalidateQueries({ queryKey: ["research-projects"] })
}

export function useResearchProjectsQuery(status?: "active" | "archived") {
  return useQuery({ queryKey: queryKeys.researchProjects(status), queryFn: () => fetchResearchProjects(status), retry: false })
}

export function useResearchProjectQuery(projectId: string) {
  return useQuery({ queryKey: queryKeys.researchProject(projectId), queryFn: () => fetchResearchProject(projectId), enabled: Boolean(projectId) })
}

export function useCreateResearchProjectMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createResearchProject,
    onSuccess: (project) => {
      queryClient.setQueryData(queryKeys.researchProject(project.id), project)
      void queryClient.invalidateQueries({ queryKey: ["research-projects"] })
    },
  })
}

export function useUpdateResearchProjectMutation(projectId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: { title?: string; description?: string }) => updateResearchProject(projectId, payload),
    onSuccess: (project) => {
      queryClient.setQueryData(queryKeys.researchProject(project.id), project)
      void queryClient.invalidateQueries({ queryKey: ["research-projects"] })
    },
  })
}

export function useDeleteResearchProjectMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteResearchProject,
    onSuccess: (_result, projectId) => {
      queryClient.removeQueries({ queryKey: queryKeys.researchProject(projectId) })
      void queryClient.invalidateQueries({ queryKey: ["research-projects"] })
    },
  })
}

export function useSetResearchProjectArchivedMutation(projectId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (archived: boolean) => setResearchProjectArchived(projectId, archived),
    onSuccess: (project) => {
      queryClient.setQueryData(queryKeys.researchProject(project.id), project)
      void queryClient.invalidateQueries({ queryKey: ["research-projects"] })
    },
  })
}

export function useResearchProjectItemsQuery(projectId: string) {
  return useQuery({ queryKey: queryKeys.researchProjectItems(projectId), queryFn: () => fetchResearchProjectItems(projectId), enabled: Boolean(projectId), refetchOnWindowFocus: "always" })
}

export function useAddResearchProjectItemMutation(projectId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (item: ResearchProjectItemInput) => addResearchProjectItem(projectId, item),
    onSuccess: () => {
      invalidateResearchProject(queryClient, projectId)
      void queryClient.invalidateQueries({ queryKey: queryKeys.researchProjectItems(projectId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.researchProjectCoverage(projectId) })
      void queryClient.invalidateQueries({ queryKey: ["research-project-backlinks"] })
    },
  })
}

export function useRemoveResearchProjectItemMutation(projectId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (itemId: string) => removeResearchProjectItem(projectId, itemId),
    onSuccess: () => {
      invalidateResearchProject(queryClient, projectId)
      void queryClient.invalidateQueries({ queryKey: queryKeys.researchProjectItems(projectId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.researchProjectCoverage(projectId) })
    },
  })
}

export function useReorderResearchProjectItemsMutation(projectId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (itemIds: string[]) => reorderResearchProjectItems(projectId, itemIds),
    onSuccess: (items) => queryClient.setQueryData(queryKeys.researchProjectItems(projectId), items),
  })
}

export function useResearchProjectCoverageQuery(projectId: string) {
  return useQuery({ queryKey: queryKeys.researchProjectCoverage(projectId), queryFn: () => fetchResearchProjectCoverage(projectId), enabled: Boolean(projectId), refetchOnWindowFocus: "always" })
}

export function useResearchProjectAnalysisQuery(projectId: string) {
  return useQuery({
    queryKey: queryKeys.researchProjectAnalysis(projectId),
    queryFn: () => fetchResearchProjectAnalysis(projectId),
    enabled: Boolean(projectId),
    refetchInterval: (query) => ["queued", "running", "cancelling"].includes(query.state.data?.run?.status ?? "") ? 1_000 : false,
  })
}

export function useStartResearchProjectAnalysisMutation(projectId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => startResearchProjectAnalysis(projectId),
    onSuccess: (analysis) => {
      queryClient.setQueryData(queryKeys.researchProjectAnalysis(projectId), analysis)
      invalidateResearchProject(queryClient, projectId)
    },
  })
}

export function useControlResearchProjectAnalysisMutation(projectId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (action: "pause" | "resume" | "cancel" | "retry") => controlResearchProjectAnalysis(projectId, action),
    onSuccess: (analysis) => {
      queryClient.setQueryData(queryKeys.researchProjectAnalysis(projectId), analysis)
      invalidateResearchProject(queryClient, projectId)
    },
  })
}

export function useResearchProjectArtifactQuery<T extends object>(projectId: string, type: ResearchProjectArtifactType, version?: number, enabled = true) {
  return useQuery({
    queryKey: queryKeys.researchProjectArtifact(projectId, type, version),
    queryFn: () => fetchResearchProjectArtifact<T>(projectId, type, version),
    enabled: Boolean(projectId) && enabled,
    refetchOnWindowFocus: "always",
  })
}

export function useResearchProjectArtifactVersionsQuery(projectId: string, type: ResearchProjectArtifactType) {
  return useQuery({ queryKey: queryKeys.researchProjectArtifactVersions(projectId, type), queryFn: () => fetchResearchProjectArtifactVersions(projectId, type), enabled: Boolean(projectId) })
}

export function useProjectEntityEvidenceQuery(projectId: string, version: number, kind: ProjectEntityEvidence["entity_kind"], entityId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["research-project", projectId, "evidence", version, kind, entityId],
    queryFn: () => fetchProjectEntityEvidence(projectId, version, kind, entityId),
    enabled: enabled && Boolean(projectId && entityId && version),
    staleTime: 0,
    refetchInterval: enabled ? 5_000 : false,
  })
}

export function useResearchProjectBacklinksQuery(item: ResearchProjectItemInput, enabled = true) {
  return useQuery({ queryKey: queryKeys.researchProjectBacklinks(item), queryFn: () => fetchResearchProjectBacklinks(item), enabled })
}

export function useResearchReportLibraryQuery() {
  return useQuery({ queryKey: queryKeys.researchReportLibrary, queryFn: fetchResearchReportLibrary, refetchOnWindowFocus: "always" })
}

export function useWorkspacesQuery() {
  return useQuery({ queryKey: queryKeys.workspaces, queryFn: fetchWorkspaces })
}

export function useGeneralChatThreadsQuery() {
  return useQuery({ queryKey: queryKeys.chatThreads, queryFn: fetchGeneralChatThreads })
}

export function useCreateGeneralChatThreadMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload?: string | { title?: string; workspaceId?: string }) => {
      const value = typeof payload === "string" ? { title: payload } : payload
      return createGeneralChatThread(value?.title, value?.workspaceId)
    },
    onSuccess: (thread) => {
      queryClient.setQueryData(queryKeys.chatThreads, (current: typeof thread[] | undefined) => [
        thread,
        ...(current ?? []).filter((item) => item.id !== thread.id),
      ])
    },
  })
}

export function useUpdateChatThreadWorkspaceMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ threadId, workspaceId }: { threadId: string; workspaceId?: string }) =>
      updateChatThreadWorkspace(threadId, workspaceId),
    onSuccess: (thread) => {
      queryClient.setQueryData(queryKeys.chatThreads, (current: typeof thread[] | undefined) =>
        (current ?? []).map((item) => item.id === thread.id ? thread : item),
      )
    },
  })
}


export function useUpdateChatThreadTitleMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ threadId, title }: { threadId: string; title: string }) =>
      updateChatThreadTitle(threadId, title),
    onSuccess: (thread) => {
      queryClient.setQueryData(queryKeys.chatThreads, (current: typeof thread[] | undefined) =>
        (current ?? []).map((item) => item.id === thread.id ? thread : item),
      )
    },
  })
}

export function useCreateWorkspaceMutation() {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: createWorkspace, onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.workspaces }) })
}

export function useUpdateWorkspaceMutation(workspaceId: string) {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: (payload: { title?: string; description?: string }) => updateWorkspace(workspaceId, payload), onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.workspaces }) })
}

export function useDeleteWorkspaceMutation() {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: deleteWorkspace, onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.workspaces }) })
}

export function useCurrentUserQuery() {
  return useQuery({
    queryKey: queryKeys.currentUser,
    queryFn: fetchCurrentUser,
    retry: false,
    staleTime: 60_000,
    refetchOnWindowFocus: true,
  })
}

export function useResearchRunsQuery() {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: queryKeys.researchRuns,
    queryFn: fetchResearchRuns,
    refetchInterval: (query) =>
      query.state.data?.some((run) => ["queued", "running", "cancelling"].includes(run.status))
        ? 1_000
        : false,
  })
  useEffect(() => {
    for (const run of query.data ?? []) {
      const current = queryClient.getQueryData<ResearchRun>(queryKeys.researchRun(run.id))
      if (current && current.state_version < run.state_version) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.researchRun(run.id) })
      }
    }
  }, [query.data, queryClient])
  return query
}

export function useResearchRunQuery(id: string) {
  return useQuery<ResearchRun>({
    queryKey: queryKeys.researchRun(id),
    queryFn: () => fetchResearchRun(id),
    enabled: id.length > 0,
    structuralSharing: (previous: unknown, incoming: unknown) => {
      const current = previous as ResearchRun | undefined
      const next = incoming as ResearchRun
      return current && current.state_version > next.state_version ? current : next
    },
  })
}

export function useResearchArtifactsQuery(id: string) {
  return useQuery({
    queryKey: queryKeys.researchArtifacts(id),
    queryFn: () => fetchResearchArtifacts(id),
    enabled: id.length > 0,
  })
}

export function useResearchRunPapersQuery(id: string) {
  return useQuery({
    queryKey: queryKeys.researchRunPapers(id),
    queryFn: () => fetchResearchRunPapers(id),
    enabled: id.length > 0,
  })
}

export function useResearchCitationsQuery(id: string) {
  return useQuery({
    queryKey: [...queryKeys.researchRun(id), "citations"],
    queryFn: () => fetchResearchCitations(id),
    enabled: id.length > 0,
    refetchOnWindowFocus: "always",
    refetchInterval: 5_000,
    refetchIntervalInBackground: false,
  })
}

export function useResearchReportsQuery(id: string) {
  return useQuery({
    queryKey: [...queryKeys.researchRun(id), "reports"],
    queryFn: () => fetchResearchReports(id),
    enabled: id.length > 0,
    refetchOnWindowFocus: "always",
    refetchInterval: 5_000,
    refetchIntervalInBackground: false,
  })
}

export function useResearchCitationEvidenceQuery(runId: string, citationId: string, enabled: boolean) {
  return useQuery({
    queryKey: [...queryKeys.researchRun(runId), "citation", citationId, "evidence"],
    queryFn: () => fetchResearchCitationEvidence(runId, citationId),
    enabled: enabled && runId.length > 0 && citationId.length > 0,
    staleTime: 0,
    refetchInterval: enabled ? 5_000 : false,
    refetchIntervalInBackground: false,
  })
}

export function useRegenerateResearchReportMutation(runId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => regenerateResearchReport(runId),
    onSuccess: (run) => {
      queryClient.setQueryData(queryKeys.researchRun(runId), run)
      void queryClient.invalidateQueries({ queryKey: queryKeys.researchRun(runId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.researchArtifacts(runId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.researchRuns })
    },
  })
}

export function useCreateResearchRunMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createResearchRun,
    onSuccess: (run) => {
      queryClient.setQueryData(queryKeys.researchRun(run.id), run)
      queryClient.invalidateQueries({ queryKey: queryKeys.researchRuns })
    },
  })
}

export function useResearchRunControlMutation(runId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (action: "pause" | "resume" | "cancel" | "retry") =>
      controlResearchRun(runId, action),
    onSuccess: (run) => {
      queryClient.setQueryData(queryKeys.researchRun(run.id), run)
      queryClient.invalidateQueries({ queryKey: queryKeys.researchRuns })
    },
  })
}

export function useResolveResearchDecisionMutation(runId: string, projectId?: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ decisionId, optionId }: { decisionId: string; optionId: string }) =>
      resolveResearchDecision(decisionId, optionId),
    onSuccess: (run) => {
      queryClient.setQueryData(queryKeys.researchRun(runId), (previous: typeof run | undefined) =>
        previous && previous.state_version > run.state_version ? previous : run)
      queryClient.invalidateQueries({ queryKey: queryKeys.researchRuns })
      if (projectId) queryClient.invalidateQueries({ queryKey: queryKeys.researchProjectAnalysis(projectId) })
    },
  })
}

export function useStatsQuery() {
  return useQuery({ queryKey: queryKeys.stats, queryFn: fetchStats })
}

export function usePapersQuery(filters: PaperFilters = {}) {
  return useQuery({
    queryKey: queryKeys.papers(filters),
    queryFn: () => fetchPapers(filters),
    refetchInterval: (query) => query.state.data?.some((paper) =>
      ["queued", "download", "parse", "index", "retry_wait"].includes(paper.preparation.status)
    ) ? 2_000 : false,
  })
}

export function usePaperQuery(id: number) {
  return useQuery({
    queryKey: queryKeys.paper(id),
    queryFn: () => fetchPaperDetail(id),
    enabled: Number.isFinite(id) && id > 0,
    refetchInterval: (query) => {
      const status = query.state.data?.preparation.status
      return status && ["queued", "download", "parse", "index", "retry_wait"].includes(status) ? 2_000 : false
    },
  })
}

export function usePaperChunksQuery(id: number, enabled = true) {
  return useQuery({
    queryKey: queryKeys.paperChunks(id),
    queryFn: () => fetchPaperChunks(id),
    enabled: enabled && Number.isFinite(id) && id > 0,
  })
}

export function useWikiSearchQuery(q: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.wikiSearch(q),
    queryFn: () => searchWiki(q),
    enabled: enabled && q.trim().length > 0,
  })
}

export function useGraphQuery(topic: string) {
  return useQuery({
    queryKey: queryKeys.graph({ topic }),
    queryFn: () => fetchGraph(topic),
  })
}

export function useHistoryQuery() {
  return useQuery({ queryKey: queryKeys.history, queryFn: fetchHistory })
}

export function useSubscriptionsQuery() {
  return useQuery({ queryKey: queryKeys.subscriptions, queryFn: fetchSubscriptions })
}

export function useLibraryFoldersQuery() {
  return useQuery({ queryKey: queryKeys.libraryFolders, queryFn: fetchLibraryFolders, retry: false })
}

export function useLibraryItemsQuery(folderId?: number) {
  return useQuery({ queryKey: queryKeys.libraryItems(folderId), queryFn: () => fetchLibraryItems(folderId), retry: false })
}

export function useIngestArxivMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ingestArxiv,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["papers"] })
      queryClient.invalidateQueries({ queryKey: queryKeys.stats })
      queryClient.invalidateQueries({ queryKey: ["graph"] })
    },
  })
}


export function useCreateLibraryFolderMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createLibraryFolder,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.libraryFolders }),
  })
}

export function useDeleteLibraryFolderMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteLibraryFolder,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.libraryFolders }),
  })
}

export function useMoveLibraryItemMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ itemId, folderId }: { itemId: number; folderId: number }) => moveLibraryItem(itemId, folderId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["library-items"] })
      queryClient.invalidateQueries({ queryKey: queryKeys.libraryFolders })
    },
  })
}

export function useRecommendLibraryFolderMutation() {
  return useMutation({ mutationFn: recommendLibraryFolder })
}

export function useIngestSourceMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ source, ...payload }: { source: "usenix" | "sigops"; venue: string; year: number; max_results: number }) =>
      ingestSource(source, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["papers"] })
      queryClient.invalidateQueries({ queryKey: queryKeys.stats })
    },
  })
}

export function useUploadPaperMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ file, title, authors, year, visibility }: {
      file: File
      title?: string
      authors?: string
      year?: number
      visibility?: "private" | "public"
    }) => uploadPaper(file, { title, authors, year, visibility }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["papers"] })
      queryClient.invalidateQueries({ queryKey: queryKeys.stats })
    },
  })
}

export function useFavoriteMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ paperId, favorite }: { paperId: number; favorite: boolean }) =>
      toggleFavorite(paperId, favorite),
    onSuccess: (paper) => {
      queryClient.invalidateQueries({ queryKey: ["papers"] })
      queryClient.invalidateQueries({ queryKey: queryKeys.paper(paper.id) })
      queryClient.invalidateQueries({ queryKey: queryKeys.stats })
      queryClient.invalidateQueries({ queryKey: ["library-items"] })
      queryClient.invalidateQueries({ queryKey: queryKeys.libraryFolders })
    },
  })
}

export function useProcessPaperMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: processPaper,
    onSuccess: (paper) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.paper(paper.id) })
      queryClient.invalidateQueries({ queryKey: ["papers"] })
      queryClient.invalidateQueries({ queryKey: queryKeys.stats })
      queryClient.invalidateQueries({ queryKey: ["graph"] })
    },
  })
}

export function useParsePaperDocumentMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: parsePaperDocument,
    onSuccess: (result, paperId) => {
      void result
      queryClient.invalidateQueries({ queryKey: queryKeys.paper(paperId) })
      queryClient.invalidateQueries({ queryKey: queryKeys.paperChunks(paperId) })
    },
  })
}

export function useGeneratePaperSummaryMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: generatePaperSummary,
    onSuccess: (summary, paperId) => {
      void summary
      queryClient.invalidateQueries({ queryKey: queryKeys.paper(paperId) })
    },
  })
}

export function useAddNoteMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ paperId, note, comment }: { paperId: number; note: string; comment?: string }) =>
      addNote(paperId, note, comment),
    onSuccess: (note) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.paper(note.paper_id) })
      queryClient.invalidateQueries({ queryKey: queryKeys.stats })
      queryClient.invalidateQueries({ queryKey: queryKeys.history })
    },
  })
}

export function useAddSubscriptionMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ topic }: { topic: string }) => addSubscription(topic),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.subscriptions })
    },
  })
}

export function useAskQuestionMutation() {
  return useMutation({
    mutationKey: queryKeys.qa,
    mutationFn: ({ question, paperIds = [], mode = "agentic" }: { question: string; paperIds?: number[]; mode?: "agentic" | "classic" }) =>
      askQuestion(question, paperIds, mode),
  })
}
