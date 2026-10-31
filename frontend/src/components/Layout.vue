<script setup lang="ts">
import { onErrorCaptured, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { MessageSquare, Database, PanelLeftClose, PanelLeftOpen } from 'lucide-vue-next'

const route = useRoute()
const router = useRouter()
const routeError = ref('')
const sidebarCollapsed = ref(localStorage.getItem('layoutSidebarCollapsed') === 'true')

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
  localStorage.setItem('layoutSidebarCollapsed', String(sidebarCollapsed.value))
}

router.onError((error) => {
  console.error('路由加载失败:', error)
  routeError.value = error instanceof Error ? error.message : '页面组件加载失败'
})

router.afterEach((_to, _from, failure) => {
  if (!failure) routeError.value = ''
})

onErrorCaptured((error) => {
  console.error('页面渲染失败:', error)
  routeError.value = error instanceof Error ? error.message : '页面暂时无法显示'
  return false
})

function retryRoute() {
  window.location.reload()
}
</script>

<template>
  <div class="app-shell flex h-screen w-full overflow-hidden font-sans text-zinc-900">
    <!-- 左侧菜单栏 -->
    <aside
      class="app-sidebar flex flex-shrink-0 flex-col border-r border-zinc-200/80 bg-white transition-[width] duration-200"
      :class="sidebarCollapsed ? 'w-16' : 'w-64'"
    >
      <div class="border-b border-zinc-100" :class="sidebarCollapsed ? 'flex justify-center p-3' : 'px-6 py-6'">
        <div class="flex items-center gap-3" :class="sidebarCollapsed ? 'justify-center' : ''">
        <div
          class="flex h-9 w-9 items-center justify-center rounded-xl bg-purple-600 shadow-lg shadow-purple-600/20"
        >
          <Database class="w-5 h-5 text-white" />
        </div>
        <h1 v-if="!sidebarCollapsed"
          class="text-xl font-bold tracking-tight text-purple-600"
        >
          Second Brain
        </h1>
        </div>
        <p v-if="!sidebarCollapsed" class="mt-3 pl-12 text-[10px] font-semibold uppercase tracking-[0.16em] text-zinc-400">Personal knowledge OS</p>
      </div>

      <div class="flex justify-end px-3 pt-3">
        <button
          class="rounded-lg p-2 text-zinc-400 transition hover:bg-purple-50 hover:text-purple-600"
          :title="sidebarCollapsed ? '展开侧边栏' : '收缩侧边栏'"
          :aria-label="sidebarCollapsed ? '展开侧边栏' : '收缩侧边栏'"
          @click="toggleSidebar"
        >
          <PanelLeftOpen v-if="sidebarCollapsed" class="h-5 w-5" />
          <PanelLeftClose v-else class="h-5 w-5" />
        </button>
      </div>

      <nav class="flex-1 space-y-1 px-3 py-5">
        <router-link
          to="/chat"
          class="flex items-center gap-3 rounded-xl px-4 py-3 transition-all duration-200 group"
          :class="[
            route.path === '/chat'
              ? 'bg-purple-50 text-purple-700 shadow-sm ring-1 ring-purple-100'
              : 'text-zinc-500 hover:text-purple-600 hover:bg-purple-50/50',
          ]"
        >
          <MessageSquare
            class="w-5 h-5 transition-transform group-hover:scale-110"
            :class="route.path === '/chat' ? 'text-purple-600' : ''"
          />
          <span v-if="!sidebarCollapsed" class="font-medium text-sm">对话工作台</span>
        </router-link>

        <router-link
          to="/knowledge"
          class="flex items-center gap-3 rounded-xl px-4 py-3 transition-all duration-200 group"
          :class="[
            route.path === '/knowledge'
              ? 'bg-purple-50 text-purple-700 shadow-sm ring-1 ring-purple-100'
              : 'text-zinc-500 hover:text-purple-600 hover:bg-purple-50/50',
          ]"
        >
          <Database
            class="w-5 h-5 transition-transform group-hover:scale-110"
            :class="route.path === '/knowledge' ? 'text-purple-600' : ''"
          />
          <span v-if="!sidebarCollapsed" class="font-medium text-sm">知识库管理</span>
        </router-link>
      </nav>

    </aside>

    <!-- 右侧主区域 -->
    <main class="relative flex h-full min-w-0 flex-1 flex-col bg-[#f8f7fc]">
      <div
        class="pointer-events-none absolute inset-0 bg-gradient-to-br from-purple-50/30 via-transparent to-violet-50/20"
      ></div>
      <router-view v-slot="{ Component, route: viewRoute }">
        <section
          v-if="routeError"
          class="relative z-10 m-auto w-full max-w-lg rounded-2xl border border-amber-200 bg-white p-7 text-center shadow-lg shadow-purple-950/5"
          role="alert"
        >
          <div class="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-amber-50 text-amber-700">!</div>
          <h2 class="mt-4 text-lg font-semibold text-zinc-900">页面暂时无法显示</h2>
          <p class="mt-2 break-words text-sm leading-6 text-zinc-500">{{ routeError }}</p>
          <button
            class="mt-5 rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-purple-500"
            @click="retryRoute"
          >
            重新加载页面
          </button>
        </section>
        <component v-else-if="Component" :is="Component" :key="viewRoute.fullPath" />
        <div v-else class="relative z-10 m-auto text-sm text-zinc-500" role="status">
          页面正在加载…
        </div>
      </router-view>
    </main>
  </div>
</template>

<style scoped>
.app-shell{background:#f8f7fc}
.app-sidebar{box-shadow:4px 0 18px rgb(39 16 76/.025)}
</style>
