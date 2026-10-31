<script setup lang="ts">
import { onErrorCaptured, ref } from 'vue'

const renderError = ref('')

onErrorCaptured((error) => {
  console.error('页面渲染失败:', error)
  renderError.value = error instanceof Error ? error.message : '页面暂时无法显示'
  return false
})

function retryPage() {
  window.location.reload()
}
</script>

<template>
  <main v-if="renderError" class="flex min-h-screen items-center justify-center bg-zinc-50 p-6 text-zinc-800">
    <section class="w-full max-w-md rounded-2xl border border-zinc-200 bg-white p-7 text-center shadow-lg shadow-purple-950/5">
      <div class="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-rose-50 text-rose-600">!</div>
      <h1 class="mt-4 text-lg font-semibold">页面暂时无法显示</h1>
      <p class="mt-2 break-words text-sm leading-6 text-zinc-500">{{ renderError }}</p>
      <button class="mt-5 rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-purple-500" @click="retryPage">重新加载页面</button>
    </section>
  </main>
  <router-view v-else />
</template>
