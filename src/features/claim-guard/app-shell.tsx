import { useState, type CSSProperties, type ReactNode } from "react"
import {
  ArchiveIcon,
  CheckCircle2Icon,
  ChevronRightIcon,
  ClipboardCheckIcon,
  FileClockIcon,
  FileScanIcon,
  FileTextIcon,
  FolderSearch2Icon,
  GaugeIcon,
  BarChart3Icon,
  LayoutDashboardIcon,
  LibraryBigIcon,
  SearchCheckIcon,
  Share2Icon,
  Settings2Icon,
} from "lucide-react"

import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarRail,
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar"

import type { LiabilityStatus, ScreenId } from "./types"

const primaryNavigation = [
  { id: "upload-processing", label: "Documents", icon: FileTextIcon },
  {
    id: "benchmark-dashboard",
    label: "Benchmarks",
    icon: BarChart3Icon,
  },
  {
    id: "price-comparison",
    label: "Challenged invoices",
    icon: SearchCheckIcon,
  },
  {
    id: "challenge-review",
    label: "Challenge decision",
    icon: ClipboardCheckIcon,
  },
] satisfies Array<{
  id: ScreenId
  label: string
  icon: typeof LayoutDashboardIcon
}>

const administration = [
  { id: "document-pages", label: "Source document", icon: FileScanIcon },
  {
    id: "ontology-mapping",
    label: "Repair item matching",
    icon: FolderSearch2Icon,
  },
  { id: "missing-items", label: "Manual review", icon: GaugeIcon },
  { id: "ontology-bank", label: "External price library", icon: LibraryBigIcon },
  { id: "knowledge-graph", label: "Knowledge graph", icon: Share2Icon },
] satisfies Array<{
  id: ScreenId
  label: string
  icon: typeof LayoutDashboardIcon
}>

const documentScreens: ScreenId[] = [
  "upload-processing",
  "document-pages",
  "extracted-invoice",
]
const reviewScreens: ScreenId[] = [
  "calculation-checks",
  "ontology-mapping",
  "price-comparison",
  "missing-items",
]

function primaryActiveId(activeScreen: ScreenId): ScreenId {
  if (documentScreens.includes(activeScreen)) return "upload-processing"
  if (activeScreen === "calculation-checks") return "upload-processing"
  if (reviewScreens.includes(activeScreen)) return "price-comparison"
  if (activeScreen === "knowledge-graph") return "benchmark-dashboard"
  return activeScreen
}

function AppSidebar({
  activeScreen,
  onNavigate,
  apiMode,
}: {
  activeScreen: ScreenId
  onNavigate: (screen: ScreenId) => void
  apiMode: "api" | "demo"
}) {
  const { isMobile, setOpenMobile } = useSidebar()
  const advancedToolActive = administration.some(
    (item) => item.id === activeScreen
  )
  const [administrationOpen, setAdministrationOpen] = useState(false)
  const activePrimary = primaryActiveId(activeScreen)
  const navigate = (screen: ScreenId) => {
    onNavigate(screen)
    if (isMobile) setOpenMobile(false)
  }

  return (
    <Sidebar collapsible="icon" className="border-r-0">
      <SidebarHeader className="px-4 py-4">
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              size="lg"
              className="h-14 px-2"
              onClick={() => navigate("upload-processing")}
            >
              <span className="flex size-10 items-center justify-center rounded-lg bg-primary text-base font-bold text-primary-foreground">
                CG
              </span>
              <span className="grid min-w-0 flex-1 text-left leading-tight">
                <span className="truncate text-base font-semibold">
                  ClaimGuard
                </span>
                <span className="truncate text-xs text-muted-foreground">
                  Motor claims review
                </span>
              </span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent className="px-2">
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu className="gap-1">
              {primaryNavigation.map((item) => {
                const Icon = item.icon
                return (
                  <SidebarMenuItem key={item.id}>
                    <SidebarMenuButton
                      size="lg"
                      className="h-11 rounded-lg"
                      isActive={activePrimary === item.id}
                      onClick={() => navigate(item.id)}
                      tooltip={item.label}
                    >
                      <Icon aria-hidden />
                      <span>{item.label}</span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                )
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup>
          <SidebarGroupLabel>Case records</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton
                  size="lg"
                  className="h-11 rounded-lg"
                  isActive={activeScreen === "audit-reports"}
                  onClick={() => navigate("audit-reports")}
                  tooltip="Audit trail"
                >
                  <FileClockIcon aria-hidden />
                  <span>Audit trail</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <Collapsible
          open={administrationOpen || advancedToolActive}
          onOpenChange={setAdministrationOpen}
        >
          <SidebarGroup>
            <SidebarGroupLabel asChild>
              <CollapsibleTrigger className="group/admin w-full cursor-pointer">
                <Settings2Icon aria-hidden />
                <span>Advanced tools</span>
                <ChevronRightIcon
                  className="ml-auto transition-transform group-data-[state=open]/admin:rotate-90"
                  aria-hidden
                />
              </CollapsibleTrigger>
            </SidebarGroupLabel>
            <CollapsibleContent>
              <SidebarGroupContent>
                <SidebarMenu className="mt-2 gap-1">
                  {administration.map((item) => {
                    const Icon = item.icon
                    return (
                      <SidebarMenuItem key={item.id}>
                        <SidebarMenuButton
                          isActive={activeScreen === item.id}
                          onClick={() => navigate(item.id)}
                          tooltip={item.label}
                        >
                          <Icon aria-hidden />
                          <span>{item.label}</span>
                        </SidebarMenuButton>
                      </SidebarMenuItem>
                    )
                  })}
                </SidebarMenu>
              </SidebarGroupContent>
            </CollapsibleContent>
          </SidebarGroup>
        </Collapsible>
      </SidebarContent>

      <SidebarFooter className="px-3 pb-4">
        <SidebarMenu className="gap-2">
          <SidebarMenuItem>
            <SidebarMenuButton className="text-xs text-muted-foreground">
              {apiMode === "api" ? (
                <CheckCircle2Icon className="text-success" aria-hidden />
              ) : (
                <ArchiveIcon aria-hidden />
              )}
              <span>
                {apiMode === "api" ? "API connected" : "Demo workspace"}
              </span>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" className="h-12">
              <Avatar className="size-8">
                <AvatarFallback>VC</AvatarFallback>
              </Avatar>
              <span className="grid min-w-0 flex-1 text-left leading-tight">
                <span className="truncate text-sm font-medium">
                  Pilot Handler
                </span>
                <span className="truncate text-xs text-muted-foreground">
                  Claims handler
                </span>
              </span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}

export function AppShell({
  activeScreen,
  onNavigate,
  apiMode,
  children,
}: {
  activeScreen: ScreenId
  onNavigate: (screen: ScreenId) => void
  issuanceAllowed: boolean
  liabilityStatus: LiabilityStatus
  apiMode: "api" | "demo"
  children: ReactNode
}) {
  return (
    <SidebarProvider style={{ "--sidebar-width": "18rem" } as CSSProperties}>
      <AppSidebar
        activeScreen={activeScreen}
        onNavigate={onNavigate}
        apiMode={apiMode}
      />
      <SidebarInset className="min-w-0 overflow-hidden bg-background">
        <header className="flex h-14 shrink-0 items-center border-b px-4 md:hidden">
          <SidebarTrigger />
          <span className="ml-3 text-sm font-semibold">ClaimGuard</span>
        </header>
        <main className="min-h-0 flex-1 overflow-y-auto bg-background">
          <div className="mx-auto flex w-full max-w-[1280px] flex-col gap-6 px-5 py-8 lg:px-10 lg:py-10">
            {children}
          </div>
        </main>
      </SidebarInset>
    </SidebarProvider>
  )
}
