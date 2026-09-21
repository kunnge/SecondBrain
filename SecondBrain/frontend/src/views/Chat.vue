<template>
  <div class="flex-1 flex flex-col h-full bg-zinc-50 text-zinc-900 relative overflow-hidden">
    <!-- 头部 -->
    <header
      class="h-16 border-b border-zinc-200 flex items-center justify-between px-6 bg-white/80 backdrop-blur-md z-10"
    >
      <div class="flex items-center gap-2">
        <h2 class="text-lg font-semibold tracking-tight text-zinc-800">对话工作台</h2>
        <span
          class="px-2 py-0.5 rounded-full bg-purple-100 text-purple-600 text-[10px] font-bold uppercase tracking-wider border border-purple-200"
        >
          V1.0
        </span>
      </div>
      <button
        @click="chatStore.clearMessages"
        class="p-2 text-zinc-400 hover:text-rose-500 hover:bg-rose-50 rounded-lg transition-all"
        title="清空对话"
      >
        <Trash2 class="w-5 h-5" />
      </button>
    </header>

    <!-- 消息列表滚动区 -->
    <main ref="scrollContainer" class="flex-1 overflow-y-auto p-6 scroll-smooth">
      <div class="max-w-4xl mx-auto space-y-8 pb-32" v-auto-animate>
        <template v-if="chatStore.messages.length > 0">
          <div
            v-for="msg in chatStore.messages"
            :key="msg.id"
            class="flex gap-4 group animate-in fade-in slide-in-from-bottom-2 duration-300"
            :class="msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'"
          >
            <!-- 头像 -->
            <div
              class="w-10 h-10 rounded-xl flex-shrink-0 flex items-center justify-center shadow-md"
              :class="msg.role === 'user' ? 'bg-purple-600' : 'bg-white border border-zinc-200'"
            >
              <User v-if="msg.role === 'user'" class="w-6 h-6 text-white" />
              <Bot v-else class="w-6 h-6 text-purple-600" />
            </div>

            <!-- 消息气泡 -->
            <div
              class="max-w-[80%] rounded-2xl px-5 py-3 transition-all"
              :class="[
                msg.role === 'user'
                  ? 'bg-purple-600 text-white rounded-tr-none shadow-purple-600/10 shadow-lg'
                  : 'bg-white border border-zinc-200 text-zinc-700 rounded-tl-none shadow-sm',
              ]"
            >
              <MarkdownRenderer :content="msg.content" />

              <div
                v-if="msg.role === 'assistant' && msg.sources && msg.sources.length > 0"
                class="mt-4 pt-4 border-t border-zinc-100 flex flex-col gap-3"
              >
                <!-- 来源小标题 -->
                <div class="flex items-center gap-1.5 text-xs text-zinc-400 font-medium">
                  <BookOpen class="w-3.5 h-3.5" />
                  <span>参考来源</span>
                </div>

                <!-- 来源卡片列表 -->
                <div class="grid grid-cols-1 gap-2">
                  <div
                    v-for="(source, idx) in msg.sources"
                    :key="source.id || idx"
                    class="bg-zinc-50/80 hover:bg-purple-50/50 transition-all duration-300 rounded-xl p-3 border border-zinc-100 text-xs group/source"
                  >
                    <!-- 卡片头部：文件名和类型 -->
                    <div
                      class="font-semibold text-purple-700 mb-1.5 flex items-center justify-between"
                    >
                      <span class="truncate pr-2">{{ source.filename || '未知文档' }}</span>
                      <span
                        class="text-[10px] text-zinc-400 font-normal bg-zinc-200/50 px-1.5 py-0.5 rounded flex-shrink-0"
                      >
                        {{ source.node_type || '文本片段' }}
                      </span>
                    </div>
                    <!-- 卡片内容：默认折叠两行，hover时展开全量文本 -->
                    <div
                      class="text-zinc-500 line-clamp-2 leading-relaxed group-hover/source:line-clamp-none transition-all duration-300"
                      :title="source.content"
                    >
                      {{ source.content }}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </template>

        <!-- 空状态 -->
        <div v-else class="flex flex-col items-center justify-center py-20 text-center">
          <div
            class="w-16 h-16 rounded-2xl bg-white border border-zinc-200 flex items-center justify-center mb-6 shadow-sm"
          >
            <Bot class="w-8 h-8 text-purple-600" />
          </div>
          <h3 class="text-xl font-bold text-zinc-800 mb-2">欢迎来到 Second Brain</h3>
          <p class="text-zinc-500 max-w-sm leading-relaxed">
            你可以问我任何问题，或者上传 Markdown 文档到知识库让我为你解答。
          </p>
        </div>
      </div>
    </main>

    <!-- 固定输入区 -->
    <footer
      class="absolute bottom-0 left-0 right-0 p-6 bg-gradient-to-t from-zinc-50 via-zinc-50 to-transparent"
    >
      <div class="max-w-4xl mx-auto relative group">
        <div
          class="absolute -inset-1 bg-gradient-to-r from-purple-400 to-purple-600 rounded-2xl blur opacity-10 group-focus-within:opacity-20 transition duration-1000"
        ></div>
        <div
          class="relative flex items-end gap-3 bg-white border border-zinc-200 rounded-2xl p-3 shadow-xl backdrop-blur-xl"
        >
          <textarea
            ref="textareaRef"
            v-model="inputContent"
            rows="1"
            placeholder="输入你的问题..."
            class="flex-1 bg-transparent border-none text-zinc-800 placeholder-zinc-400 px-3 py-2 focus:outline-none resize-none max-h-52 min-h-[44px] overflow-y-auto leading-6"
            @keydown="handleKeydown"
            @input="autoResize"
          />
          <button
            @click="handleSend"
            :disabled="!inputContent.trim() || chatStore.isSending"
            class="w-10 h-10 rounded-xl bg-purple-600 flex items-center justify-center text-white shadow-lg shadow-purple-600/20 hover:bg-purple-500 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
          >
            <Send class="w-5 h-5" />
          </button>
        </div>
        <p class="text-[10px] text-zinc-400 mt-2 text-center">
          按 Enter 发送，按 Shift + Enter 换行
        </p>
      </div>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { Send, User, Bot, Trash2, BookOpen } from 'lucide-vue-next'
import { useChatStore } from '@/stores/chat'
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'

const chatStore = useChatStore()
const inputContent = ref('')
const scrollContainer = ref<HTMLElement | null>(null)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
//增加键盘处理函数
const handleKeydown = (event: KeyboardEvent) => {
  // Shift + Enter 换行
  if (event.key === 'Enter' && event.shiftKey) {
    return
  }

  // Enter 发送
  if (event.key === 'Enter') {
    event.preventDefault()
    handleSend()
  }
}
//实现 textarea 自动高度
const autoResize = () => {
  const textarea = textareaRef.value

  if (!textarea) return

  // 先恢复高度，重新计算
  textarea.style.height = 'auto'

  // 内容高度
  const height = textarea.scrollHeight

  // 最大高度 160px
  textarea.style.height = Math.min(height, 200) + 'px'
}

const handleSend = async () => {
  if (!inputContent.value.trim() || chatStore.isSending) return

  const content = inputContent.value

  inputContent.value = ''

  // 恢复输入框高度
  nextTick(() => {
    if (textareaRef.value) {
      textareaRef.value.style.height = '44px'
    }
  })

  await chatStore.sendMessage(content)
}

// 触底滚动函数
const scrollToBottom = (behavior: ScrollBehavior = 'smooth') => {
  if (scrollContainer.value) {
    scrollContainer.value.scrollTo({
      top: scrollContainer.value.scrollHeight,
      behavior,
    })
  }
}

// 监听消息变化自动滚动
let observer: MutationObserver | null = null

onMounted(() => {
  if (scrollContainer.value) {
    observer = new MutationObserver(() => {
      scrollToBottom('smooth')
    })
    observer.observe(scrollContainer.value, {
      childList: true,
      subtree: true,
      characterData: true,
    })
  }
  scrollToBottom('auto')
})

onUnmounted(() => {
  if (observer) {
    observer.disconnect()
  }
})
</script>

<style scoped>
/* 隐藏滚动条但保留功能 */
::-webkit-scrollbar {
  width: 6px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  @apply bg-zinc-800 rounded-full;
}

::-webkit-scrollbar-thumb:hover {
  @apply bg-zinc-700;
}
</style>
