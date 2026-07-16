import {
  BookMarked,
  Brain,
  Library,
  Menu,
  MessageSquareText,
  LogOut,
} from "lucide-react"
import { useQueryClient } from "@tanstack/react-query"
import type { ComponentType, SVGProps } from "react"
import { Link, NavLink, Outlet, useLocation } from "react-router"
import { ThemeToggle } from "@/components/app/theme-toggle"
import { TaskCenter } from "@/features/research/task-center"
import { Button } from "@/components/ui/button"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarSeparator,
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar"
import { cn } from "@/lib/utils"
import { logout } from "@/api"
import { queryKeys, useCurrentUserQuery } from "@/lib/query-hooks"

type NavItem = {
  path: string
  label: string
  description: string
  icon: ComponentType<SVGProps<SVGSVGElement>>
}

const navItems: NavItem[] = [
  { path: "/", label: "Chat", description: "通用对话", icon: MessageSquareText },
  { path: "/papers", label: "论文库", description: "检索与同步", icon: Library },
  { path: "/library", label: "我的资料库", description: "收藏与目录", icon: BookMarked },
]

function BrandLink() {
  return (
    <Link
      to="/"
      className="flex min-h-14 items-center gap-3 rounded-lg px-2 text-left transition-colors hover:bg-sidebar-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <span className="grid size-10 place-items-center rounded-lg bg-primary text-primary-foreground">
        <Brain className="size-5" />
      </span>
      <span className="min-w-0">
        <span className="block truncate text-sm font-semibold text-sidebar-foreground">PaperWiki</span>
        <span className="block truncate text-xs text-sidebar-foreground/60">开放研究工作台</span>
      </span>
    </Link>
  )
}

function NavigationMenu() {
  const { setOpenMobile } = useSidebar()
  const location = useLocation()

  return (
    <SidebarMenu>
      {navItems.map((item) => {
        const Icon = item.icon
        const active = item.path === "/" ? location.pathname === "/" : location.pathname.startsWith(item.path)

        return (
          <SidebarMenuItem key={item.path}>
            <SidebarMenuButton
              asChild
              isActive={active}
              size="lg"
              tooltip={item.label}
              className="min-h-12"
            >
              <NavLink to={item.path} onClick={() => setOpenMobile(false)}>
                <Icon className="size-4" />
                <span>{item.label}</span>
              </NavLink>
            </SidebarMenuButton>
          </SidebarMenuItem>
        )
      })}
    </SidebarMenu>
  )
}

export function AppShell() {
  const queryClient = useQueryClient()
  const userQuery = useCurrentUserQuery()
  const location = useLocation()
  const header = location.pathname.startsWith("/runs/")
    ? { title: "Research Run", description: "可恢复任务与执行步骤" }
    : location.pathname.startsWith("/papers")
      ? { title: "论文库", description: "检索、导入与阅读论文" }
      : location.pathname.startsWith("/library")
        ? { title: "我的资料库", description: "收藏与研究资料" }
        : { title: "PaperWiki Chat", description: "从对话开始你的研究" }

  const signOut = async () => {
    await logout()
    queryClient.removeQueries({
      predicate: (query) => query.queryKey[0] !== queryKeys.currentUser[0],
    })
    queryClient.setQueryData(queryKeys.currentUser, null)
  }

  return (
    <SidebarProvider>
      <a
        href="#main-content"
        className="sr-only z-50 rounded-md bg-background px-3 py-2 text-sm font-medium text-foreground focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:ring-2 focus:ring-ring"
      >
        跳到主内容
      </a>

      <Sidebar collapsible="offcanvas" className="border-r">
        <SidebarHeader className="p-3">
          <BrandLink />
        </SidebarHeader>
        <SidebarSeparator />
        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupContent>
              <NavigationMenu />
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>
        <SidebarFooter className="p-3">
          <div className="flex items-center justify-between gap-2 rounded-lg border px-3 py-2">
            <span className="truncate text-sm font-medium">{userQuery.data?.username}</span>
            <Button variant="ghost" size="icon" aria-label="退出登录" onClick={signOut}>
              <LogOut className="size-4" />
            </Button>
          </div>
          <div className="rounded-lg border bg-sidebar-accent/40 p-3 text-xs leading-5 text-sidebar-foreground/70">
            <span className="font-semibold text-sidebar-foreground">当前阶段</span>
            <p className="mt-1">Research Harness 已接入；论文调研 Agent 与报告链路将按迭代逐步开放。</p>
          </div>
        </SidebarFooter>
      </Sidebar>

      <SidebarInset className="min-w-0">
        <header className="sticky top-0 z-20 flex min-h-16 items-center justify-between border-b bg-background/90 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/80 lg:px-6">
          <div className="flex items-center gap-2">
            <SidebarTrigger className={cn("size-11 md:hidden")} aria-label="打开导航">
              <Menu className="size-4" />
            </SidebarTrigger>
            <div>
              <p className="text-sm font-semibold text-foreground">{header.title}</p>
              <p className="text-xs text-muted-foreground">{header.description}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <TaskCenter />
            <Button asChild variant="outline" className="hidden h-11 sm:inline-flex">
              <Link to="/papers">检索论文</Link>
            </Button>
            <ThemeToggle />
          </div>
        </header>

        <main id="main-content" className="min-w-0 flex-1 px-3 py-3 lg:px-5 lg:py-4">
          <div className="mx-auto grid w-full max-w-[1480px] gap-5">
            <Outlet />
          </div>
        </main>
      </SidebarInset>
    </SidebarProvider>
  )
}
