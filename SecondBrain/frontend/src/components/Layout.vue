<script setup lang="ts">
import { useRoute } from 'vue-router'
import { MessageSquare, Database } from 'lucide-vue-next'

const route = useRoute()
</script>

<template>
  <div class="flex h-screen w-full bg-zinc-50 text-zinc-900 overflow-hidden font-sans">
    <!-- 左侧菜单栏 -->
    <aside
      class="w-64 flex-shrink-0 bg-white border-r border-zinc-200 flex flex-col h-full transition-all"
    >
      <div class="p-6 flex items-center gap-3">
        <div
          class="w-8 h-8 rounded-lg bg-purple-600 flex items-center justify-center shadow-lg shadow-purple-600/20"
        >
          <Database class="w-5 h-5 text-white" />
        </div>
        <h1
          class="font-bold tracking-tight text-xl bg-clip-text text-transparent bg-gradient-to-r from-purple-600 to-purple-400"
        >
          Second Brain
        </h1>
      </div>

      <nav class="flex-1 px-4 py-4 space-y-2">
        <router-link
          to="/chat"
          class="flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-200 group"
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
          class="flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-200 group"
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

      <div class="p-4 mt-auto">
        <div class="p-4 rounded-xl bg-purple-50/50 border border-purple-100 text-xs text-zinc-500">
          <p class="font-medium text-purple-700 mb-1">系统状态</p>
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
    <main class="flex-1 flex flex-col h-full min-w-0 bg-zinc-50 relative">
      <div
        class="absolute inset-0 bg-[url('https://grainy-gradients.vercel.app/noise.svg')] opacity-[0.015] pointer-events-none mix-blend-overlay"
      ></div>
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
  </div>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition:
    opacity 0.2s ease,
    transform 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
  transform: translateY(4px);
}
</style>
