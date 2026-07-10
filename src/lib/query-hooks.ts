import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  addNote,
  addSubscription,
  askQuestion,
  fetchGraph,
  fetchHistory,
  fetchPaperDetail,
  fetchPapers,
  fetchStats,
  fetchSubscriptions,
  ingestArxiv,
  ingestSource,
  processPaper,
  searchWiki,
  toggleFavorite,
  uploadPaper,
} from "@/api"

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
  stats: ["stats"] as const,
  papers: (filters: PaperFilters = {}) => ["papers", filters] as const,
  paper: (id: number) => ["paper", id] as const,
  wikiSearch: (q: string) => ["wiki-search", q] as const,
  qa: ["qa"] as const,
  graph: (filters: GraphFilters = {}) => ["graph", filters] as const,
  history: ["history"] as const,
  subscriptions: ["subscriptions"] as const,
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
    mutationFn: ({ file, title, authors, year }: { file: File; title?: string; authors?: string; year?: number }) =>
      uploadPaper(file, { title, authors, year }),
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
    mutationFn: ({ question, paperIds = [] }: { question: string; paperIds?: number[] }) =>
      askQuestion(question, paperIds),
  })
}
