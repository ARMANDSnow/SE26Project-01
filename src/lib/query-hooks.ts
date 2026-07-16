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
  createResearchRun,
  controlResearchRun,
  resolveResearchDecision,
  fetchGeneralChatThreads,
  createGeneralChatThread,
} from "@/api"
import type { ResearchRun } from "@/types"

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
  chatThreads: ["chat-threads"] as const,
}

export function useGeneralChatThreadsQuery() {
  return useQuery({ queryKey: queryKeys.chatThreads, queryFn: fetchGeneralChatThreads })
}

export function useCreateGeneralChatThreadMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (title?: string) => createGeneralChatThread(title),
    onSuccess: (thread) => {
      queryClient.setQueryData(queryKeys.chatThreads, (current: typeof thread[] | undefined) => [
        thread,
        ...(current ?? []).filter((item) => item.id !== thread.id),
      ])
    },
  })
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

export function useResolveResearchDecisionMutation(runId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ decisionId, optionId }: { decisionId: string; optionId: string }) =>
      resolveResearchDecision(decisionId, optionId),
    onSuccess: (run) => {
      queryClient.setQueryData(queryKeys.researchRun(runId), (previous: typeof run | undefined) =>
        previous && previous.state_version > run.state_version ? previous : run)
      queryClient.invalidateQueries({ queryKey: queryKeys.researchRuns })
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
  })
}

export function usePaperQuery(id: number) {
  return useQuery({
    queryKey: queryKeys.paper(id),
    queryFn: () => fetchPaperDetail(id),
    enabled: Number.isFinite(id) && id > 0,
  })
}

export function usePaperChunksQuery(id: number) {
  return useQuery({
    queryKey: queryKeys.paperChunks(id),
    queryFn: () => fetchPaperChunks(id),
    enabled: Number.isFinite(id) && id > 0,
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
  return useQuery({ queryKey: queryKeys.libraryFolders, queryFn: fetchLibraryFolders })
}

export function useLibraryItemsQuery(folderId?: number) {
  return useQuery({ queryKey: queryKeys.libraryItems(folderId), queryFn: () => fetchLibraryItems(folderId) })
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
    onSuccess: (document, paperId) => {
      void document
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
