import { useState, type CSSProperties, type ReactNode } from "react"
import {
  CheckCircle2Icon,
  ChevronRightIcon,
  PlugZapIcon,
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

import { activeEntryId, advancedTools, navigationSections } from "./navigation"
import type { LiabilityStatus, ScreenId } from "./types"

const PRODUCT_NAME = "Price Benchmarking Model TP Repair"

/** How the app is currently placed against the ClaimGuard API. There is no
 * "demo" state: the footer reports the real connection, never a stand-in. */
export type ApiStatus = "connecting" | "connected" | "unavailable"

const API_STATUS_LABELS: Record<ApiStatus, string> = {
  connecting: "Connecting to the API",
  connected: "API connected",
  unavailable: "API unavailable",
}

function AppSidebar({
  activeScreen,
  onNavigate,
  apiStatus,
}: {
  activeScreen: ScreenId
  onNavigate: (screen: ScreenId) => void
  apiStatus: ApiStatus
}) {
  const { isMobile, setOpenMobile } = useSidebar()
  const activeEntry = activeEntryId(activeScreen)
  const advancedToolActive = advancedTools.some(
    (item) => item.id === activeEntry
  )
  const [administrationOpen, setAdministrationOpen] = useState(false)
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
              onClick={() => navigate("tp-upload")}
            >
              <span className="flex size-10 items-center justify-center rounded-lg bg-[#f97316] text-base font-bold text-white">
                TP
              </span>
              <span className="grid min-w-0 flex-1 text-left leading-tight">
                <span className="truncate text-base font-semibold text-[#f97316]">
                  {PRODUCT_NAME}
                </span>
                <span className="truncate text-xs text-muted-foreground">
                  Motor claims price benchmarking
                </span>
              </span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent className="px-2">
        {navigationSections.map((section) => (
          <SidebarGroup key={section.id}>
            <SidebarGroupLabel className="text-sm font-bold text-[#f97316] dark:text-orange-400">
              {section.label}
            </SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu className="gap-1">
                {section.items.map((item) => {
                  const Icon = item.icon
                  return (
                    <SidebarMenuItem key={item.id}>
                      <SidebarMenuButton
                        className="h-9 rounded-lg"
                        isActive={activeEntry === item.id}
                        onClick={() => navigate(item.id)}
                        // The same three sub-screen names recur under every
                        // heading, so the collapsed-rail tooltip carries the
                        // heading too.
                        tooltip={`${section.label} · ${item.label}`}
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
        ))}

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
                  {advancedTools.map((item) => {
                    const Icon = item.icon
                    return (
                      <SidebarMenuItem key={item.id}>
                        <SidebarMenuButton
                          isActive={activeEntry === item.id}
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
              {apiStatus === "connected" ? (
                <CheckCircle2Icon className="text-success" aria-hidden />
              ) : (
                <PlugZapIcon aria-hidden />
              )}
              <span>{API_STATUS_LABELS[apiStatus]}</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" className="h-12">
              <Avatar className="size-8">
                <AvatarFallback>CG</AvatarFallback>
              </Avatar>
              <span className="grid min-w-0 flex-1 text-left leading-tight">
                <span className="truncate text-sm font-medium">
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
  apiStatus,
  children,
}: {
  activeScreen: ScreenId
  onNavigate: (screen: ScreenId) => void
  issuanceAllowed: boolean
  liabilityStatus: LiabilityStatus
  apiStatus: ApiStatus
  children: ReactNode
}) {
  return (
    <SidebarProvider style={{ "--sidebar-width": "18rem" } as CSSProperties}>
      <AppSidebar
        activeScreen={activeScreen}
        onNavigate={onNavigate}
        apiStatus={apiStatus}
      />
      <SidebarInset className="min-w-0 overflow-hidden bg-background">
        <header className="flex h-14 shrink-0 items-center border-b px-4 md:hidden">
          <SidebarTrigger />
          <span className="ml-3 text-sm font-semibold text-[#f97316]">
            {PRODUCT_NAME}
          </span>
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
