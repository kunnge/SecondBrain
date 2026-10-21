<script setup lang="ts">
import { onErrorCaptured, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { MessageSquare, Database } from 'lucide-vue-next'

const route = useRoute()
const router = useRouter()
const routeError = ref('')

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
      class="app-sidebar flex w-64 flex-shrink-0 flex-col border-r border-zinc-200/80 bg-white transition-all"
    >
      <div class="border-b border-zinc-100 px-6 py-6">
        <div class="flex items-center gap-3">
        <div
          class="flex h-9 w-9 items-center justify-center rounded-xl bg-purple-600 shadow-lg shadow-purple-600/20"
        >
          <Database class="w-5 h-5 text-white" />
        </div>
        <h1
          class="text-xl font-bold tracking-tight text-purple-600"
        >
          Second Brain
        </h1>
        </div>
        <p class="mt-3 pl-12 text-[10px] font-semibold uppercase tracking-[0.16em] text-zinc-400">Personal knowledge OS</p>
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
          <span class="font-medium text-sm">对话工作台</span>
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
          <span class="font-medium text-sm">知识库管理</span>
        </router-link>
      </nav>

      <div class="mt-auto p-4">
        <div class="rounded-xl border border-purple-100 bg-purple-50/60 p-4 text-xs text-zinc-500">
          <div class="mb-2 flex items-center justify-between"><p class="font-medium text-purple-700">系统状态</p><span class="rounded-full bg-white px-2 py-0.5 text-[10px] font-semibold text-purple-600">ONLINE</span></div>
          <p class="flex items-center gap-2">
            <span
              class="w-2 h-2 rounded-full bg-purple-500 shadow-[0_0_8px_rgba(168,85,247,0.4)]"
            ></span>
            引擎运行中
          </p>
        </div>
      </div>
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
