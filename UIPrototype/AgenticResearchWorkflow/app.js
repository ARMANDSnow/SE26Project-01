const body = document.body
const root = document.documentElement
const sidebar = document.querySelector(".sidebar")
const workflowPanel = document.querySelector("#workflow-panel")
const taskDrawer = document.querySelector(".task-drawer")
const decisionDialog = document.querySelector(".decision-dialog")
const commandDialog = document.querySelector(".command-dialog")
const toast = document.querySelector(".toast")
const composer = document.querySelector("#composer-input")
const messages = document.querySelector("#messages")
let toastTimer
let runSeconds = 8 * 60 + 42

function iconUse(button, iconId) {
  const use = button?.querySelector("use")
  if (use) use.setAttribute("href", iconId)
}

function showToast(title, description = "") {
  toast.querySelector("strong").textContent = title
  toast.querySelector("small").textContent = description
  toast.classList.add("visible")
  window.clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => toast.classList.remove("visible"), 3200)
}

function closeOverlays() {
  body.classList.remove("tasks-open", "decision-open", "command-open", "sidebar-open", "workflow-open")
  taskDrawer.setAttribute("aria-hidden", "true")
  decisionDialog.setAttribute("aria-hidden", "true")
  commandDialog.setAttribute("aria-hidden", "true")
  taskDrawer.inert = true
  decisionDialog.inert = true
  commandDialog.inert = true
  window.setTimeout(syncResponsiveInert, 0)
}

function syncResponsiveInert() {
  const compactWorkflow = window.matchMedia("(max-width: 1180px)").matches
  const mobileSidebar = window.matchMedia("(max-width: 760px)").matches
  workflowPanel.inert = compactWorkflow && !body.classList.contains("workflow-open")
  workflowPanel.setAttribute("aria-hidden", String(workflowPanel.inert))
  sidebar.inert = mobileSidebar && !body.classList.contains("sidebar-open")
  sidebar.setAttribute("aria-hidden", String(sidebar.inert))
}

function openTasks() {
  closeOverlays()
  body.classList.add("tasks-open")
  taskDrawer.setAttribute("aria-hidden", "false")
  taskDrawer.inert = false
  window.setTimeout(() => taskDrawer.querySelector("[data-action='close-tasks']")?.focus(), 80)
}

function openDecision() {
  closeOverlays()
  body.classList.add("decision-open")
  decisionDialog.setAttribute("aria-hidden", "false")
  decisionDialog.inert = false
  window.setTimeout(() => decisionDialog.querySelector(".decision-option")?.focus(), 80)
}

function openCommand() {
  closeOverlays()
  body.classList.add("command-open")
  commandDialog.setAttribute("aria-hidden", "false")
  commandDialog.inert = false
  window.setTimeout(() => commandDialog.querySelector("input")?.focus(), 80)
}

function openWorkflow() {
  if (window.matchMedia("(max-width: 1180px)").matches) {
    closeOverlays()
    body.classList.add("workflow-open")
    syncResponsiveInert()
    workflowPanel.querySelector("[data-action='close-workflow']")?.focus()
  } else {
    const runningStep = document.querySelector(".workflow-step.running")
    runningStep?.scrollIntoView({ behavior: "smooth", block: "center" })
    runningStep?.classList.add("expanded")
    runningStep?.querySelector(".step-summary")?.setAttribute("aria-expanded", "true")
  }
}

function toggleTheme() {
  const dark = root.classList.toggle("dark")
  localStorage.setItem("paperwiki-prototype-theme", dark ? "dark" : "light")
  showToast(dark ? "已切换到深色模式" : "已切换到浅色模式", "Workflow 状态色已同步调整")
}

function toggleRun() {
  const paused = body.classList.toggle("run-paused")
  const button = document.querySelector("[data-action='pause-run']")
  const label = button.querySelector("span")
  const runStatus = document.querySelector(".run-status")
  const topStatus = document.querySelector(".topbar-title > div:last-child > span")

  if (paused) {
    label.textContent = "继续"
    iconUse(button, "#i-play")
    runStatus.classList.remove("running")
    runStatus.classList.add("paused")
    runStatus.lastChild.textContent = "已暂停"
    topStatus.innerHTML = '<span class="status-dot"></span>Research Run 已暂停'
    showToast("任务已在安全点暂停", "已完成步骤和解析结果都会保留")
  } else {
    label.textContent = "暂停"
    iconUse(button, "#i-pause")
    runStatus.classList.remove("paused")
    runStatus.classList.add("running")
    runStatus.lastChild.textContent = "正在执行"
    topStatus.innerHTML = '<span class="status-dot running"></span>Research Run 正在执行'
    showToast("任务已继续", "从“抓取与解析全文”检查点恢复")
  }
}

function appendMessage(text) {
  const message = document.createElement("div")
  message.className = "message user-message"

  const bubble = document.createElement("div")
  bubble.className = "message-bubble"
  bubble.textContent = text

  const meta = document.createElement("div")
  meta.className = "message-meta"
  meta.textContent = `你 · ${new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`
  message.append(bubble, meta)
  messages.append(message)

  const response = document.createElement("div")
  response.className = "checkpoint-message"
  response.innerHTML = '<span class="checkpoint-icon"><svg><use href="#i-check"></use></svg></span><span><strong>要求已加入当前任务</strong><small>Research Coordinator 会在后续步骤中应用，不会重新执行已经完成的检索。</small></span>'
  messages.append(response)
  messages.scrollTo({ top: messages.scrollHeight, behavior: "smooth" })
  showToast("后续要求已发送", "Agent 会从当前检查点继续")
}

document.querySelectorAll(".workflow-step button.step-summary").forEach((button) => {
  button.addEventListener("click", () => {
    const step = button.closest(".workflow-step")
    const expanded = step.classList.toggle("expanded")
    button.setAttribute("aria-expanded", String(expanded))
  })
})

document.querySelectorAll("[data-step-target]").forEach((button) => {
  button.addEventListener("click", () => {
    openWorkflow()
    const step = document.querySelector(`[data-step="${button.dataset.stepTarget}"]`)
    step?.classList.add("expanded")
    step?.querySelector(".step-summary")?.setAttribute("aria-expanded", "true")
    window.setTimeout(() => step?.scrollIntoView({ behavior: "smooth", block: "center" }), 240)
  })
})

document.querySelectorAll("[data-action]").forEach((button) => {
  button.addEventListener("click", () => {
    switch (button.dataset.action) {
      case "open-tasks":
        openTasks()
        break
      case "close-tasks":
      case "close-decision":
      case "close-workflow":
        closeOverlays()
        break
      case "open-decision":
        openDecision()
        break
      case "open-command":
        openCommand()
        break
      case "open-workflow":
        openWorkflow()
        break
      case "toggle-theme":
        toggleTheme()
        break
      case "open-sidebar":
        closeOverlays()
        body.classList.add("sidebar-open")
        syncResponsiveInert()
        break
      case "pause-run":
        toggleRun()
        break
      case "stop-run":
        showToast("停止操作需要二次确认", "高保真原型不会真正终止任务")
        break
      case "focus-current-run":
        closeOverlays()
        showToast("已定位当前任务", "RAG 检索优化调研")
        break
      case "new-research":
        closeOverlays()
        composer.value = ""
        composer.focus()
        showToast("已准备新研究", "输入主题、时间范围和关注重点")
        break
      default:
        break
    }
  })
})

document.querySelector("[data-close-overlays]").addEventListener("click", closeOverlays)

document.querySelectorAll("[data-nav]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll("[data-nav]").forEach((item) => item.classList.remove("active"))
    button.classList.add("active")
    closeOverlays()
    showToast(`已选择“${button.dataset.nav}”`, "此设计原型重点展示 Chat 与 Workflow 页面")
  })
})

document.querySelectorAll(".conversation").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".conversation").forEach((item) => item.classList.remove("active"))
    button.classList.add("active")
    if (button.querySelector(".conversation-state.waiting")) openDecision()
    else showToast("已切换模拟会话", button.querySelector("strong").textContent)
  })
})

document.querySelectorAll("[data-decision]").forEach((button) => {
  button.addEventListener("click", () => {
    const choice = button.dataset.decision
    closeOverlays()
    document.querySelector(".needs-input")?.remove()
    document.querySelector(".notification-badge")?.remove()
    const firstConversation = document.querySelectorAll(".conversation")[1]
    const state = firstConversation?.querySelector(".conversation-state")
    state?.classList.remove("waiting")
    state?.classList.add("running")
    const statusText = firstConversation?.querySelector("small")
    if (statusText) statusText.textContent = `已选择“${choice}” · 正在继续`
    showToast("范围已确认，任务继续执行", choice)
  })
})

document.querySelector("#composer-form").addEventListener("submit", (event) => {
  event.preventDefault()
  const value = composer.value.trim()
  if (!value) {
    showToast("请先输入内容", "可以补充调研范围、输出格式或关注问题")
    return
  }
  appendMessage(value)
  composer.value = ""
  composer.style.height = "auto"
})

composer.addEventListener("input", () => {
  composer.style.height = "auto"
  composer.style.height = `${Math.min(composer.scrollHeight, 130)}px`
})

composer.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault()
    document.querySelector("#composer-form").requestSubmit()
  }
})

document.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault()
    openCommand()
  }
  if (event.key === "Escape") closeOverlays()
})

window.addEventListener("resize", () => {
  if (window.innerWidth > 1180) body.classList.remove("workflow-open")
  if (window.innerWidth > 760) body.classList.remove("sidebar-open")
  syncResponsiveInert()
})

const storedTheme = localStorage.getItem("paperwiki-prototype-theme")
if (storedTheme === "dark") root.classList.add("dark")
syncResponsiveInert()

window.setInterval(() => {
  if (body.classList.contains("run-paused")) return
  runSeconds += 1
  const minutes = Math.floor(runSeconds / 60)
  const seconds = String(runSeconds % 60).padStart(2, "0")
  document.querySelector(".run-time").lastChild.textContent = `${String(minutes).padStart(2, "0")}:${seconds}`
}, 1000)
