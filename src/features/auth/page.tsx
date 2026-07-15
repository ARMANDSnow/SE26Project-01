import { useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { Brain } from "lucide-react"
import { login, register } from "@/api"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { queryKeys } from "@/lib/query-hooks"

type Mode = "login" | "register"

export function AuthPage() {
  const queryClient = useQueryClient()
  const [mode, setMode] = useState<Mode>("login")
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError("")
    try {
      const user = mode === "login"
        ? await login(username.trim(), password)
        : await register(username.trim(), password)
      queryClient.setQueryData(queryKeys.currentUser, user)
      await queryClient.invalidateQueries()
    } catch {
      setError(mode === "login" ? "用户名或密码错误。" : "注册失败，请检查用户名是否已存在。")
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="grid min-h-screen place-items-center bg-muted/30 px-4 py-10">
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-3 text-center">
          <span className="mx-auto grid size-12 place-items-center rounded-xl bg-primary text-primary-foreground">
            <Brain className="size-6" />
          </span>
          <CardTitle>PaperWiki</CardTitle>
          <CardDescription>
            {mode === "login" ? "登录后继续你的研究工作区。" : "创建一个独立的个人研究空间。"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="grid gap-4" onSubmit={submit}>
            <div className="grid gap-2">
              <Label htmlFor="username">用户名</Label>
              <Input
                id="username"
                autoComplete="username"
                minLength={mode === "register" ? 3 : 1}
                maxLength={64}
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                required
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="password">密码</Label>
              <Input
                id="password"
                type="password"
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                minLength={mode === "register" ? 8 : 1}
                maxLength={256}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </div>
            {error ? <p className="text-sm text-destructive" role="alert">{error}</p> : null}
            <Button type="submit" className="h-11" disabled={busy}>
              {busy ? "请稍候…" : mode === "login" ? "登录" : "注册并登录"}
            </Button>
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setMode(mode === "login" ? "register" : "login")
                setError("")
              }}
            >
              {mode === "login" ? "没有账户？创建账户" : "已有账户？返回登录"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  )
}
