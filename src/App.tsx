import {
  AlertCircle,
  ArrowRight,
  BarChart3,
  BookOpen,
  Bookmark,
  Brain,
  CheckCircle2,
  Clock3,
  Columns3,
  ExternalLink,
  FileText,
  GitBranch,
  LayoutDashboard,
  Library,
  Loader2,
  MessageSquareText,
  Network,
  Plus,
  RefreshCw,
  Search,
  Send,
  Sparkles,
  Star,
  Tags
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  addNote,
  askQuestion,
  fetchGraph,
  fetchHistory,
  fetchPaperDetail,
  fetchPapers,
  fetchStats,
  ingestArxiv,
  processPaper,
  searchWiki,
  toggleFavorite
} from "./api";
import type { GraphData, Paper, QaResponse, Stats, WikiSearchResult, HistoryItem } from "./types";

type Page = "dashboard" | "papers" | "detail" | "qa" | "graph" | "learning";

const navItems = [
  { path: "/", label: "仪表盘", icon: LayoutDashboard },
  { path: "/papers", label: "论文库", icon: Library },
  { path: "/qa", label: "智能问答", icon: MessageSquareText },
  { path: "/graph", label: "知识图谱", icon: Network },
  { path: "/learning", label: "学习管理", icon: Bookmark }
];

const sectionNames: Record<string, string> = {
  summary: "摘要",
  concepts: "概念",
  methods: "方法",
  experiments: "实验"
};

function useRoute() {
  const [path, setPath] = useState(window.location.pathname);
  useEffect(() => {
    const handler = () => setPath(window.location.pathname);
    window.addEventListener("popstate", handler);
    return () => window.removeEventListener("popstate", handler);
  }, []);
  const navigate = (nextPath: string) => {
    window.history.pushState({}, "", nextPath);
    setPath(nextPath);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  return { path, navigate };
}

function pageFromPath(path: string): Page {
  if (path.startsWith("/papers/")) return "detail";
  if (path.startsWith("/papers")) return "papers";
  if (path.startsWith("/qa")) return "qa";
  if (path.startsWith("/graph")) return "graph";
  if (path.startsWith("/learning")) return "learning";
  return "dashboard";
}

function StatusPill({ status }: { status: Paper["processing_status"] }) {
  const label = status === "processed" ? "已解析" : status === "pending" ? "待处理" : "失败";
  return <span className={`pill status-${status}`}>{label}</span>;
}

function IconButton({
  children,
  title,
  onClick,
  active = false,
  disabled = false
}: {
  children: React.ReactNode;
  title: string;
  onClick?: () => void;
  active?: boolean;
  disabled?: boolean;
}) {
  return (
    <button className={`icon-button ${active ? "active" : ""}`} title={title} onClick={onClick} disabled={disabled}>
      {children}
    </button>
  );
}

function Metric({ label, value, tone }: { label: string; value: number | string; tone: "teal" | "amber" | "blue" | "rose" }) {
  return (
    <div className={`metric metric-${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function MarkdownBlock({ content }: { content: string }) {
  return (
    <div className="markdown-block">
      {content.split("\n").map((line, index) => {
        const key = `${index}-${line.slice(0, 8)}`;
        if (line.startsWith("# ")) return <h3 key={key}>{line.replace("# ", "")}</h3>;
        if (line.startsWith("- ")) return <p key={key} className="bullet-line">{line}</p>;
        if (!line.trim()) return <div key={key} className="line-gap" />;
        return <p key={key}>{line}</p>;
      })}
    </div>
  );
}

function plainSnippet(content: string, limit = 130) {
  return content
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#"))
    .map((line) => line.replace(/^- /, ""))
    .join(" ")
    .slice(0, limit);
}

function PaperCard({ paper, onOpen, onFavorite }: { paper: Paper; onOpen: () => void; onFavorite?: () => void }) {
  return (
    <article className="paper-card">
      <div className="paper-card-head">
        <div className="paper-title-group">
          <span className="category-chip">{paper.primary_category}</span>
          <h3>{paper.title}</h3>
        </div>
        <div className="paper-actions">
          <IconButton title={paper.is_favorite ? "取消收藏" : "收藏"} active={paper.is_favorite} onClick={onFavorite}>
            <Star size={18} />
          </IconButton>
          <IconButton title="查看详情" onClick={onOpen}>
            <ArrowRight size={18} />
          </IconButton>
        </div>
      </div>
      <p className="abstract">{paper.abstract}</p>
      <div className="paper-meta">
        <span><BookOpen size={14} /> {paper.authors.slice(0, 3).join("、")}</span>
        <span><Clock3 size={14} /> {paper.published_at}</span>
        <StatusPill status={paper.processing_status} />
      </div>
      <div className="tag-row">
        {Array.from(new Set(paper.categories)).slice(0, 4).map((category) => (
          <span key={`${paper.id}-${category}`} className="tag">{category}</span>
        ))}
      </div>
    </article>
  );
}

function Layout({
  page,
  path,
  navigate,
  children
}: {
  page: Page;
  path: string;
  navigate: (path: string) => void;
  children: React.ReactNode;
}) {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <button className="brand" onClick={() => navigate("/")}>
          <span className="brand-mark"><Brain size={22} /></span>
          <span>
            <strong>PaperWiki</strong>
            <small>arXiv 论文学习工具</small>
          </span>
        </button>
        <nav>
          {navItems.map((item) => {
            const Icon = item.icon;
            const active = item.path === "/" ? page === "dashboard" : path.startsWith(item.path);
            return (
              <button key={item.path} className={`nav-link ${active ? "active" : ""}`} onClick={() => navigate(item.path)}>
                <Icon size={18} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>
        <div className="agent-strip">
          <span>Agent 流水线</span>
          <strong>抓取 · 阅读 · 摘要 · 校验 · 问答</strong>
        </div>
      </aside>
      <main className="content">{children}</main>
    </div>
  );
}

function Dashboard({ navigate }: { navigate: (path: string) => void }) {
  const [stats, setStats] = useState<Stats | null>(null);
  const [papers, setPapers] = useState<Paper[]>([]);
  useEffect(() => {
    fetchStats().then(setStats);
    fetchPapers({ limit: 6 }).then(setPapers);
  }, []);
  const completion = stats ? Math.round((stats.processed / Math.max(stats.papers, 1)) * 100) : 0;
  return (
    <section className="page">
      <div className="page-header compact">
        <div>
          <span className="eyebrow">科研论文知识工作台</span>
          <h1>arXiv 智能论文阅读工具</h1>
        </div>
        <div className="header-actions">
          <button className="secondary-button" onClick={() => navigate("/graph")}>
            <Network size={17} /> 知识图谱
          </button>
          <button className="primary-button" onClick={() => navigate("/qa")}>
            <MessageSquareText size={17} /> 提问
          </button>
        </div>
      </div>

      <div className="metric-grid">
        <Metric label="论文记录" value={stats?.papers ?? "···"} tone="teal" />
        <Metric label="已结构化" value={`${completion}%`} tone="blue" />
        <Metric label="概念节点" value={stats?.concepts ?? "···"} tone="amber" />
        <Metric label="收藏笔记" value={(stats?.favorites ?? 0) + (stats?.notes ?? 0)} tone="rose" />
      </div>

      <div className="dashboard-grid">
        <section className="panel">
          <div className="panel-head">
            <h2><BarChart3 size={18} /> 主题分布</h2>
            <button className="text-button" onClick={() => navigate("/papers")}>查看论文库</button>
          </div>
          <div className="category-bars">
            {(stats?.categories ?? []).map((item) => (
              <div key={item.category} className="bar-line">
                <span>{item.category}</span>
                <div className="bar-track">
                  <div style={{ width: `${Math.min(100, (item.count / Math.max(stats?.papers ?? 1, 1)) * 220)}%` }} />
                </div>
                <strong>{item.count}</strong>
              </div>
            ))}
          </div>
        </section>

        <section className="panel">
          <div className="panel-head">
            <h2><GitBranch size={18} /> 处理流水线</h2>
            <span className="pill status-processed">运行中</span>
          </div>
          <div className="pipeline">
            {["FetcherAgent", "ReaderAgent", "SummaryAgent", "ValidatorAgent", "QAAgent"].map((agent, index) => (
              <div key={agent} className="pipeline-step">
                <span>{index + 1}</span>
                <strong>{agent}</strong>
              </div>
            ))}
          </div>
        </section>
      </div>

      <section className="panel">
        <div className="panel-head">
          <h2><FileText size={18} /> 最新论文</h2>
          <button className="text-button" onClick={() => navigate("/papers")}>全部论文</button>
        </div>
        <div className="paper-list two-column">
          {papers.slice(0, 6).map((paper) => (
            <PaperCard key={paper.id} paper={paper} onOpen={() => navigate(`/papers/${paper.id}`)} />
          ))}
        </div>
      </section>
    </section>
  );
}

function PapersPage({ navigate }: { navigate: (path: string) => void }) {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");
  const [concept, setConcept] = useState("");
  const [favoriteOnly, setFavoriteOnly] = useState(false);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  const load = () => {
    setLoading(true);
    fetchPapers({ q, category, concept, favorite: favoriteOnly, limit: 80 })
      .then(setPapers)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, []);

  const categories = useMemo(() => Array.from(new Set(papers.flatMap((paper) => paper.categories))).slice(0, 8), [papers]);

  const onIngest = async () => {
    setLoading(true);
    setMessage("");
    try {
      const keywords = q ? q.split(/\s+/).filter(Boolean) : ["RAG"];
      const result = await ingestArxiv({ categories: category ? [category] : [], keywords, max_results: 8 });
      setMessage(`已从 arXiv 同步 ${result.count} 篇论文`);
      await fetchPapers({ q, category, concept, limit: 80 }).then(setPapers);
    } catch (error) {
      setMessage(error instanceof Error ? "arXiv 抓取失败，当前仍可使用内置样例数据" : "抓取失败");
    } finally {
      setLoading(false);
    }
  };

  const onFavorite = async (paper: Paper) => {
    const updated = await toggleFavorite(paper.id, !paper.is_favorite);
    setPapers((items) => items.map((item) => (item.id === paper.id ? { ...item, is_favorite: updated.is_favorite } : item)));
  };

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <span className="eyebrow">论文自动抓取与管理</span>
          <h1>论文库</h1>
        </div>
        <button className="primary-button" onClick={onIngest} disabled={loading}>
          {loading ? <Loader2 size={17} className="spin" /> : <RefreshCw size={17} />} 同步 arXiv
        </button>
      </div>

      <section className="toolbar">
        <label className="search-field">
          <Search size={18} />
          <input value={q} onChange={(event) => setQ(event.target.value)} placeholder="搜索标题、作者、摘要、关键词" />
        </label>
        <select value={category} onChange={(event) => setCategory(event.target.value)}>
          <option value="">全部分类</option>
          {categories.map((item) => <option key={item} value={item}>{item}</option>)}
          <option value="cs.AI">cs.AI</option>
          <option value="cs.CL">cs.CL</option>
          <option value="cs.LG">cs.LG</option>
        </select>
        <input className="compact-input" value={concept} onChange={(event) => setConcept(event.target.value)} placeholder="概念标签" />
        <label className="toggle">
          <input type="checkbox" checked={favoriteOnly} onChange={(event) => setFavoriteOnly(event.target.checked)} />
          <span>仅收藏</span>
        </label>
        <button className="secondary-button" onClick={load} disabled={loading}>
          <Search size={17} /> 检索
        </button>
      </section>

      {message && <div className="notice"><AlertCircle size={17} /> {message}</div>}

      <div className="paper-list">
        {papers.map((paper) => (
          <PaperCard key={paper.id} paper={paper} onOpen={() => navigate(`/papers/${paper.id}`)} onFavorite={() => onFavorite(paper)} />
        ))}
      </div>
    </section>
  );
}

function PaperDetailPage({ path, navigate }: { path: string; navigate: (path: string) => void }) {
  const pathParts = path.split("/").filter(Boolean);
  const paperId = Number(pathParts[pathParts.length - 1]);
  const [paper, setPaper] = useState<Paper | null>(null);
  const [activeSection, setActiveSection] = useState("summary");
  const [note, setNote] = useState("");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetchPaperDetail(paperId).then((detail) => {
      setPaper(detail);
      setActiveSection(detail.wiki?.[0]?.section ?? "summary");
    });
  }, [paperId]);

  if (!paper) {
    return <section className="page"><div className="loading-line"><Loader2 className="spin" /> 正在加载论文详情</div></section>;
  }

  const activeWiki = paper.wiki?.find((section) => section.section === activeSection) ?? paper.wiki?.[0];

  const onProcess = async () => {
    setBusy(true);
    try {
      const updated = await processPaper(paper.id);
      setPaper(updated);
      setActiveSection(updated.wiki?.[0]?.section ?? "summary");
    } finally {
      setBusy(false);
    }
  };

  const onFavorite = async () => {
    const updated = await toggleFavorite(paper.id, !paper.is_favorite);
    setPaper({ ...paper, is_favorite: updated.is_favorite });
  };

  const onSubmitNote = async (event: FormEvent) => {
    event.preventDefault();
    if (!note.trim()) return;
    setBusy(true);
    try {
      const saved = await addNote(paper.id, note, comment);
      setPaper({ ...paper, notes: [saved, ...(paper.notes ?? [])], reading_status: "reading" });
      setNote("");
      setComment("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="page">
      <div className="detail-header">
        <button className="text-button" onClick={() => navigate("/papers")}>返回论文库</button>
        <div className="detail-title-line">
          <div>
            <span className="category-chip">{paper.primary_category}</span>
            <h1>{paper.title}</h1>
          </div>
          <div className="paper-actions">
            <IconButton title={paper.is_favorite ? "取消收藏" : "收藏"} active={paper.is_favorite} onClick={onFavorite}>
              <Star size={18} />
            </IconButton>
            <button className="secondary-button" onClick={onProcess} disabled={busy}>
              {busy ? <Loader2 className="spin" size={17} /> : <Sparkles size={17} />} 结构化解析
            </button>
          </div>
        </div>
        <p>{paper.abstract}</p>
        <div className="paper-meta wide">
          <span><BookOpen size={14} /> {paper.authors.join("、")}</span>
          <span><Clock3 size={14} /> {paper.published_at}</span>
          <StatusPill status={paper.processing_status} />
          {paper.arxiv_url && <a href={paper.arxiv_url} target="_blank" rel="noreferrer"><ExternalLink size={14} /> arXiv</a>}
          {paper.pdf_url && <a href={paper.pdf_url} target="_blank" rel="noreferrer"><FileText size={14} /> PDF</a>}
        </div>
      </div>

      <div className="detail-grid">
        <section className="panel wiki-panel">
          <div className="tabs">
            {(paper.wiki ?? []).map((section) => (
              <button key={section.section} className={activeSection === section.section ? "active" : ""} onClick={() => setActiveSection(section.section)}>
                {sectionNames[section.section] ?? section.section}
              </button>
            ))}
          </div>
          {activeWiki ? <MarkdownBlock content={activeWiki.content} /> : <div className="empty-state">这篇论文还未生成 Wiki 内容。</div>}
        </section>

        <aside className="side-stack">
          <section className="panel">
            <div className="panel-head"><h2><Tags size={18} /> 概念标签</h2></div>
            <div className="concept-list">
              {(paper.concepts ?? []).map((concept) => (
                <div key={concept.id} className="concept-row">
                  <strong>{concept.name}</strong>
                  <span>{concept.relation} · {(concept.weight * 100).toFixed(0)}%</span>
                </div>
              ))}
            </div>
          </section>

          <section className="panel">
            <div className="panel-head"><h2><Bookmark size={18} /> 笔记</h2></div>
            <form className="note-form" onSubmit={onSubmitNote}>
              <textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="记录阅读笔记" />
              <input value={comment} onChange={(event) => setComment(event.target.value)} placeholder="评论或对比点" />
              <button className="primary-button" disabled={busy}><Plus size={17} /> 保存</button>
            </form>
            <div className="note-list">
              {(paper.notes ?? []).map((item) => (
                <div key={item.id} className="note-item">
                  <p>{item.note}</p>
                  {item.comment && <span>{item.comment}</span>}
                </div>
              ))}
            </div>
          </section>
        </aside>
      </div>
    </section>
  );
}

function QAPage({ navigate }: { navigate: (path: string) => void }) {
  const [question, setQuestion] = useState("RAG 如何保证论文问答的出处可靠？");
  const [answer, setAnswer] = useState<QaResponse | null>(null);
  const [results, setResults] = useState<WikiSearchResult[]>([]);
  const [loading, setLoading] = useState(false);

  const onAsk = async (event?: FormEvent) => {
    event?.preventDefault();
    if (!question.trim()) return;
    setLoading(true);
    const [qa, search] = await Promise.all([askQuestion(question), searchWiki(question)]);
    setAnswer(qa);
    setResults(search);
    setLoading(false);
  };

  useEffect(() => {
    onAsk();
  }, []);

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <span className="eyebrow">带出处的自然语言问答</span>
          <h1>智能问答</h1>
        </div>
      </div>
      <form className="qa-box" onSubmit={onAsk}>
        <MessageSquareText size={22} />
        <input value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="围绕论文、概念、方法或研究脉络提问" />
        <button className="primary-button" disabled={loading}>
          {loading ? <Loader2 className="spin" size={17} /> : <Send size={17} />} 发送
        </button>
      </form>

      <div className="qa-grid">
        <section className="panel answer-panel">
          <div className="panel-head">
            <h2><Brain size={18} /> 回答</h2>
            {answer && <span className="pill status-processed">置信度 {(answer.confidence * 100).toFixed(0)}%</span>}
          </div>
          {answer ? (
            <>
              <MarkdownBlock content={answer.answer} />
              <div className="agent-trace">
                {answer.agent_trace.map((agent) => <span key={agent}>{agent}</span>)}
              </div>
            </>
          ) : (
            <div className="empty-state">等待问题输入。</div>
          )}
        </section>

        <section className="panel evidence-panel">
          <div className="panel-head"><h2><CheckCircle2 size={18} /> 证据片段</h2></div>
          <div className="evidence-list">
            {(answer?.citations.length ? answer.citations : results).map((item) => (
              <button key={`${item.paper_id}-${item.section}`} className="evidence-item" onClick={() => navigate(`/papers/${item.paper_id}`)}>
                <strong>{item.paper_title}</strong>
                <span>{item.section_title} · 匹配度 {(item.score * 100).toFixed(0)}%</span>
                <p>{plainSnippet(item.content)}</p>
              </button>
            ))}
          </div>
        </section>
      </div>
    </section>
  );
}

function GraphPage({ navigate }: { navigate: (path: string) => void }) {
  const [topic, setTopic] = useState("RAG");
  const [graph, setGraph] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(false);

  const loadGraph = () => {
    setLoading(true);
    fetchGraph(topic).then(setGraph).finally(() => setLoading(false));
  };

  useEffect(() => {
    loadGraph();
  }, []);

  const layout = useMemo(() => {
    const nodes = graph?.nodes ?? [];
    const centerX = 450;
    const centerY = 250;
    const conceptNodes = nodes.filter((node) => node.type === "concept");
    const paperNodes = nodes.filter((node) => node.type === "paper");
    const positions = new Map<string, { x: number; y: number }>();
    conceptNodes.forEach((node, index) => {
      const angle = (Math.PI * 2 * index) / Math.max(conceptNodes.length, 1);
      positions.set(node.id, { x: centerX + Math.cos(angle) * 190, y: centerY + Math.sin(angle) * 150 });
    });
    paperNodes.forEach((node, index) => {
      const angle = (Math.PI * 2 * index) / Math.max(paperNodes.length, 1) + Math.PI / 8;
      positions.set(node.id, { x: centerX + Math.cos(angle) * 320, y: centerY + Math.sin(angle) * 220 });
    });
    return positions;
  }, [graph]);

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <span className="eyebrow">论文概念可视化</span>
          <h1>知识图谱</h1>
        </div>
        <div className="header-actions">
          <input className="compact-input" value={topic} onChange={(event) => setTopic(event.target.value)} placeholder="研究主题" />
          <button className="secondary-button" onClick={loadGraph} disabled={loading}>
            {loading ? <Loader2 size={17} className="spin" /> : <Search size={17} />} 刷新
          </button>
        </div>
      </div>

      <section className="graph-surface">
        <svg viewBox="0 0 900 520" role="img" aria-label="论文概念知识图谱">
          {(graph?.links ?? []).map((link, index) => {
            const source = layout.get(link.source);
            const target = layout.get(link.target);
            if (!source || !target) return null;
            return <line key={`${link.source}-${link.target}-${index}`} x1={source.x} y1={source.y} x2={target.x} y2={target.y} className="graph-link" />;
          })}
          {(graph?.nodes ?? []).map((node) => {
            const position = layout.get(node.id);
            if (!position) return null;
            const radius = node.type === "concept" ? Math.min(34, 18 + node.weight * 1.2) : 14;
            return (
              <g key={node.id} className={`graph-node ${node.type}`} onClick={() => node.type === "paper" && navigate(`/papers/${node.id.replace("p-", "")}`)}>
                <circle cx={position.x} cy={position.y} r={radius} />
                <text x={position.x} y={position.y + radius + 18}>{node.label.length > 18 ? `${node.label.slice(0, 18)}…` : node.label}</text>
              </g>
            );
          })}
        </svg>
      </section>
    </section>
  );
}

function LearningPage({ navigate }: { navigate: (path: string) => void }) {
  const [favorites, setFavorites] = useState<Paper[]>([]);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [leftId, setLeftId] = useState<number | null>(null);
  const [rightId, setRightId] = useState<number | null>(null);

  useEffect(() => {
    fetchPapers({ favorite: true, limit: 40 }).then((items) => {
      setFavorites(items);
      setLeftId(items[0]?.id ?? null);
      setRightId(items[1]?.id ?? items[0]?.id ?? null);
    });
    fetchHistory().then(setHistory);
  }, []);

  const left = favorites.find((paper) => paper.id === leftId);
  const right = favorites.find((paper) => paper.id === rightId);

  return (
    <section className="page">
      <div className="page-header">
        <div>
          <span className="eyebrow">收藏、笔记、历史与对比阅读</span>
          <h1>学习管理</h1>
        </div>
      </div>

      <div className="learning-grid">
        <section className="panel">
          <div className="panel-head"><h2><Star size={18} /> 收藏论文</h2></div>
          <div className="compact-list">
            {favorites.slice(0, 10).map((paper) => (
              <button key={paper.id} onClick={() => navigate(`/papers/${paper.id}`)}>
                <strong>{paper.title}</strong>
                <span>{paper.primary_category} · {paper.published_at}</span>
              </button>
            ))}
          </div>
        </section>

        <section className="panel">
          <div className="panel-head"><h2><Clock3 size={18} /> 阅读历史</h2></div>
          <div className="timeline">
            {history.map((item) => (
              <button key={item.id} onClick={() => navigate(`/papers/${item.paper_id}`)}>
                <span>{item.action}</span>
                <strong>{item.title}</strong>
                <small>{item.created_at}</small>
              </button>
            ))}
          </div>
        </section>
      </div>

      <section className="panel">
        <div className="panel-head"><h2><Columns3 size={18} /> 对比阅读</h2></div>
        <div className="compare-selects">
          <select value={leftId ?? ""} onChange={(event) => setLeftId(Number(event.target.value))}>
            {favorites.map((paper) => <option key={paper.id} value={paper.id}>{paper.title}</option>)}
          </select>
          <select value={rightId ?? ""} onChange={(event) => setRightId(Number(event.target.value))}>
            {favorites.map((paper) => <option key={paper.id} value={paper.id}>{paper.title}</option>)}
          </select>
        </div>
        <div className="compare-grid">
          {[left, right].map((paper, index) => (
            <article key={index} className="compare-column">
              {paper ? (
                <>
                  <span className="category-chip">{paper.primary_category}</span>
                  <h3>{paper.title}</h3>
                  <p>{paper.abstract}</p>
                  <div className="tag-row">{Array.from(new Set(paper.categories)).map((category) => <span key={`${paper.id}-${category}`} className="tag">{category}</span>)}</div>
                </>
              ) : (
                <div className="empty-state">暂无收藏论文。</div>
              )}
            </article>
          ))}
        </div>
      </section>
    </section>
  );
}

export default function App() {
  const { path, navigate } = useRoute();
  const page = pageFromPath(path);
  return (
    <Layout page={page} path={path} navigate={navigate}>
      {page === "dashboard" && <Dashboard navigate={navigate} />}
      {page === "papers" && <PapersPage navigate={navigate} />}
      {page === "detail" && <PaperDetailPage path={path} navigate={navigate} />}
      {page === "qa" && <QAPage navigate={navigate} />}
      {page === "graph" && <GraphPage navigate={navigate} />}
      {page === "learning" && <LearningPage navigate={navigate} />}
    </Layout>
  );
}
