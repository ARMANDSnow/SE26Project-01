import type { GraphData, Paper, QaResponse, Stats, WikiSearchResult, HistoryItem, Subscription } from "./types";

const wiki = [
  {
    section: "summary",
    title: "summary.md",
    content: "# 摘要\n\n论文围绕科研论文学习中的检索增强生成，提出从 arXiv 元数据、摘要和概念标签构建可追溯 Wiki。"
  },
  {
    section: "concepts",
    title: "concepts.md",
    content: "# 核心概念\n\n- RAG：将检索结果注入生成过程。\n- Evidence Grounding：答案需要绑定论文出处。"
  },
  {
    section: "methods",
    title: "methods.md",
    content: "# 方法\n\n系统通过抓取、结构化摘要、概念抽取和混合检索完成论文知识沉淀。"
  },
  {
    section: "experiments",
    title: "experiments.md",
    content: "# 实验结论\n\n检索和出处校验能够提升跨论文学习效率，并降低幻觉风险。"
  }
];

export const mockPapers: Paper[] = Array.from({ length: 12 }, (_, index) => {
  const themes = ["RAG", "多智能体", "知识图谱", "长上下文", "联邦学习", "因果发现"];
  const theme = themes[index % themes.length];
  return {
    id: index + 1,
    arxiv_id: `2501.${(1000 + index).toString().padStart(5, "0")}`,
    title: `${theme} 在科研论文阅读中的结构化学习框架`,
    authors: [`Chen ${String.fromCharCode(65 + index)}.`, `Wang ${String.fromCharCode(70 + index)}.`],
    abstract: `本文研究 ${theme} 在 arXiv 论文学习场景中的应用，支持结构化摘要、概念关联、带出处问答和阅读管理。`,
    categories: [index % 2 === 0 ? "cs.CL" : "cs.AI", "cs.IR"],
    primary_category: index % 2 === 0 ? "cs.CL" : "cs.AI",
    published_at: `2025-0${(index % 8) + 1}-12`,
    pdf_url: `https://arxiv.org/pdf/2501.${(1000 + index).toString().padStart(5, "0")}`,
    arxiv_url: `https://arxiv.org/abs/2501.${(1000 + index).toString().padStart(5, "0")}`,
    processing_status: index < 8 ? "processed" : "pending",
    reading_status: index % 3 === 0 ? "reading" : "unread",
    is_favorite: index % 4 === 0,
    wiki,
    concepts: [
      { id: index * 3 + 1, name: theme, description: "研究主题标签", relation: "主题", weight: 1 },
      { id: index * 3 + 2, name: "Evidence Grounding", description: "答案绑定出处", relation: "问答约束", weight: 0.8 }
    ],
    notes: index % 4 === 0
      ? [{ id: index + 1, paper_id: index + 1, note: "适合放入研究脉络图。", comment: "关注方法章节", created_at: "2025-06-01" }]
      : []
  };
});

export const mockStats: Stats = {
  papers: 100,
  processed: 60,
  favorites: 12,
  concepts: 32,
  notes: 8,
  categories: [
    { category: "cs.AI", count: 42 },
    { category: "cs.CL", count: 31 },
    { category: "cs.LG", count: 27 }
  ]
};

export const mockGraph: GraphData = {
  nodes: [
    { id: "c-1", label: "RAG", type: "concept", description: "检索增强生成", weight: 9 },
    { id: "c-2", label: "Evidence Grounding", type: "concept", description: "出处校验", weight: 8 },
    { id: "c-3", label: "知识图谱", type: "concept", description: "概念关系", weight: 7 },
    { id: "c-4", label: "多智能体", type: "concept", description: "协同处理流水线", weight: 6 },
    { id: "p-1", label: mockPapers[0].title, type: "paper", category: "cs.CL", weight: 1 },
    { id: "p-2", label: mockPapers[1].title, type: "paper", category: "cs.AI", weight: 1 }
  ],
  links: [
    { source: "c-1", target: "c-2", relation: "支撑", weight: 0.9 },
    { source: "c-2", target: "c-3", relation: "沉淀为", weight: 0.7 },
    { source: "c-4", target: "c-1", relation: "协同处理", weight: 0.8 },
    { source: "p-1", target: "c-1", relation: "核心概念", weight: 1 },
    { source: "p-2", target: "c-4", relation: "方法", weight: 1 }
  ]
};

export const mockSearchResults: WikiSearchResult[] = mockPapers.slice(0, 4).map((paper, index) => ({
  id: index + 1,
  paper_id: paper.id,
  paper_title: paper.title,
  arxiv_id: paper.arxiv_id,
  arxiv_url: paper.arxiv_url,
  pdf_url: paper.pdf_url,
  primary_category: paper.primary_category,
  section: "summary",
  section_title: "summary.md",
  content: paper.wiki?.[0].content ?? "",
  score: 0.86 - index * 0.08
}));

export const mockQa: QaResponse = {
  answer:
    "基于当前论文 Wiki，可以得到以下结论：\n\n1. RAG 类论文通常通过检索论文片段约束回答范围。\n2. Evidence Grounding 要求答案返回论文标题、章节和相关内容。\n3. 结构化 Wiki 能将摘要、方法和实验结论变成可复用知识。",
  citations: mockSearchResults,
  confidence: 0.82,
  agent_trace: ["QAAgent", "HybridRetriever", "EvidenceValidator"]
};

export const mockHistory: HistoryItem[] = mockPapers.slice(0, 6).map((paper, index) => ({
  id: index + 1,
  action: index % 2 === 0 ? "阅读论文详情" : "新增笔记",
  created_at: `2025-06-${(12 + index).toString().padStart(2, "0")}`,
  paper_id: paper.id,
  title: paper.title,
  primary_category: paper.primary_category
}));

export const mockSubscriptions: Subscription[] = ["大语言模型", "RAG", "多智能体", "知识图谱"].map((topic, index) => ({
  id: index + 1,
  topic,
  created_at: `2025-06-${(8 + index).toString().padStart(2, "0")}`
}));
