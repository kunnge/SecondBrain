<template>
  <div
    class="chat-root relative flex h-full min-h-0 flex-1 flex-col overflow-hidden bg-zinc-50 text-zinc-900"
  >
    <header
      class="z-10 flex h-16 shrink-0 items-center justify-between border-b border-zinc-200 bg-white/90 px-4 backdrop-blur md:px-6"
    >
      <div class="flex min-w-0 items-center gap-3">
        <button
          class="rounded-lg p-2 text-zinc-500 hover:bg-zinc-100 md:hidden"
          title="打开会话列表"
          aria-label="打开会话列表"
          @click="sidebarOpen = !sidebarOpen"
        >
          <PanelLeft class="h-5 w-5" />
        </button>
        <div class="min-w-0">
          <div class="flex items-center gap-2">
            <h2 class="truncate text-base font-semibold tracking-tight text-zinc-800">
              {{ chatStore.activeConversation?.title || '对话工作台' }}
            </h2>
            <span
              class="hidden rounded-full border border-purple-200 bg-purple-100 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-purple-600 sm:inline-flex"
            >
              Second Brain
            </span>
          </div>
          <p class="text-xs text-zinc-400">基于个人知识库回答</p>
        </div>
      </div>
      <button
        v-if="chatStore.activeConversationId"
        class="rounded-lg p-2 text-zinc-400 transition hover:bg-rose-50 hover:text-rose-500"
        title="删除当前会话"
        aria-label="删除当前会话"
        @click="deleteConversation(chatStore.activeConversationId)"
      >
        <Trash2 class="h-5 w-5" />
      </button>
    </header>

    <div class="chat-body relative flex min-h-0 flex-1 overflow-hidden">
      <button
        v-if="sidebarOpen"
        class="absolute inset-0 z-20 cursor-default bg-black/30 md:hidden"
        aria-label="关闭会话列表"
        @click="sidebarOpen = false"
      />
      <aside
        :class="
          sidebarOpen
            ? 'absolute inset-y-0 left-0 z-30 flex w-72 flex-col border-r border-zinc-200 bg-white shadow-xl md:relative md:z-auto md:w-64 md:shadow-none'
            : 'hidden w-64 shrink-0 flex-col border-r border-zinc-200 bg-white md:flex'
        "
      >
        <div class="p-3">
          <button
            class="flex w-full items-center justify-center gap-2 rounded-xl border border-zinc-200 px-3 py-2.5 text-sm font-medium text-zinc-700 transition hover:border-purple-200 hover:bg-purple-50 hover:text-purple-700"
            @click="newConversation"
          >
            <Plus class="h-4 w-4" />
            新建对话
          </button>
        </div>
        <div
          class="px-4 pb-2 pt-1 text-[11px] font-semibold uppercase tracking-wider text-zinc-400"
        >
          最近对话
        </div>
        <div class="min-h-0 flex-1 space-y-1 overflow-y-auto px-2 pb-3">
          <div
            v-for="conversation in chatStore.conversations"
            :key="conversation.id"
            class="conversation-row group"
            :class="
              conversation.id === chatStore.activeConversationId ? 'conversation-row-active' : ''
            "
          >
            <button
              class="min-w-0 flex-1 truncate px-2 py-2 text-left text-sm"
              :title="conversation.title"
              @click="openConversation(conversation.id)"
            >
              <span class="block truncate">{{ conversation.title || '新对话' }}</span>
            </button>
            <div class="conversation-actions flex shrink-0 items-center gap-0.5 pr-1">
              <button
                class="rounded-md p-1.5 text-zinc-400 hover:bg-white hover:text-purple-600"
                title="重命名会话"
                aria-label="重命名会话"
                @click.stop="renameConversation(conversation.id, conversation.title)"
              >
                <Pencil class="h-3.5 w-3.5" />
              </button>
              <button
                class="rounded-md p-1.5 text-zinc-400 hover:bg-white hover:text-rose-500"
                title="删除会话"
                aria-label="删除会话"
                @click.stop="deleteConversation(conversation.id)"
              >
                <Trash2 class="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
          <p
            v-if="!chatStore.conversations.length && !chatStore.isLoading"
            class="px-3 py-5 text-center text-xs text-zinc-400"
          >
            还没有对话
          </p>
          <p v-if="chatStore.isLoading" class="px-3 py-5 text-center text-xs text-zinc-400">
            正在加载…
          </p>
        </div>
        <div class="border-t border-zinc-100 px-4 py-3 text-[11px] leading-relaxed text-zinc-400">
          对话记录保存在本地知识库数据库中。
        </div>
      </aside>

      <section class="flex min-w-0 flex-1 flex-col">
        <main
          ref="scrollContainer"
          class="min-h-0 flex-1 overflow-x-hidden overflow-y-auto scroll-smooth px-4 py-6 md:px-6"
        >
          <div class="mx-auto max-w-4xl space-y-7 pb-4">
            <div
              v-if="chatStore.errorMessage"
              class="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700"
            >
              {{ chatStore.errorMessage }}
            </div>

            <template v-if="chatStore.messages.length">
              <div
                v-for="(msg, index) in chatStore.messages"
                :key="msg.id"
                class="group flex gap-3 md:gap-4"
                :class="msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'"
              >
                <div
                  class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl shadow-sm"
                  :class="msg.role === 'user' ? 'bg-purple-600' : 'border border-zinc-200 bg-white'"
                >
                  <User v-if="msg.role === 'user'" class="h-5 w-5 text-white" />
                  <Bot v-else class="h-5 w-5 text-purple-600" />
                </div>

                <div
                  class="flex max-w-[88%] min-w-0 flex-col gap-2 md:max-w-[82%]"
                  :class="msg.role === 'user' ? 'items-end' : 'items-start'"
                >
                  <div
                    class="min-w-0 max-w-full rounded-2xl px-4 py-3 md:px-5"
                    :class="
                      msg.role === 'user'
                        ? 'rounded-tr-sm bg-purple-200 text-white shadow-lg shadow-purple-600/10'
                        : 'rounded-tl-sm border border-zinc-200 bg-white text-zinc-700 shadow-sm'
                    "
                  >
                    <template v-if="editingMessageId === msg.id">
                      <textarea
                        v-model="editingContent"
                        rows="3"
                        class="w-full min-w-[min(65vw,24rem)] resize-y rounded-lg border border-purple-200 bg-white px-3 py-2 text-sm text-zinc-800 outline-none focus:ring-2 focus:ring-purple-200"
                        @keydown.esc="cancelEdit"
                      />
                      <div class="mt-2 flex justify-end gap-2 text-xs">
                        <button
                          class="rounded-md px-2.5 py-1.5 text-zinc-500 hover:bg-zinc-100"
                          @click="cancelEdit"
                        >
                          取消
                        </button>
                        <button
                          class="rounded-md bg-purple-600 px-2.5 py-1.5 font-medium text-white hover:bg-purple-700 disabled:opacity-50"
                          :disabled="!editingContent.trim() || chatStore.isSending"
                          @click="saveEdit(msg.id)"
                        >
                          保存并重答
                        </button>
                      </div>
                    </template>
                    <MarkdownRenderer
                      v-else
                      :content="msg.content || (msg.status === 'streaming' ? '正在生成回答…' : '')"
                    />

                    <p
                      v-if="msg.role === 'assistant' && msg.status === 'stopped'"
                      class="mt-2 text-xs text-amber-600"
                    >
                      已停止生成。你可以继续提问或重新生成回答。
                    </p>
                    <p
                      v-else-if="
                        msg.role === 'assistant' &&
                        (msg.status === 'failed' || msg.status === 'interrupted')
                      "
                      class="mt-2 text-xs text-rose-600"
                    >
                      {{ msg.error_message || '回答中断，可以重新生成。' }}
                    </p>

                    <div
                      v-if="msg.role === 'assistant' && msg.sources?.length"
                      class="mt-4 flex flex-col gap-3 border-t border-zinc-100 pt-4"
                    >
                      <div class="flex items-center gap-1.5 text-xs font-medium text-zinc-500">
                        <BookOpen class="h-3.5 w-3.5 shrink-0" />
                        <span>参考来源</span>
                        <span class="text-zinc-400">{{ msg.sources.length }}</span>
                      </div>
                      <div class="grid grid-cols-1 gap-2">
                        <div
                          v-for="(source, sourceIndex) in msg.sources"
                          :key="source.id || sourceIndex"
                          class="rounded-xl border border-zinc-100 bg-zinc-50/80 p-3 text-xs transition hover:bg-purple-50/50"
                        >
                          <div class="flex items-center justify-between gap-3">
                            <div
                              class="flex min-w-0 items-center gap-2 font-semibold text-purple-700"
                            >
                              <FileText class="h-3.5 w-3.5 shrink-0" />
                              <span class="truncate">{{ source.filename || '未知文档' }}</span>
                              <span
                                class="hidden shrink-0 text-[10px] font-normal text-zinc-400 sm:inline"
                              >
                                {{ source.heading_path || source.node_type || '知识片段' }}
                              </span>
                            </div>
                            <button
                              class="flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-xs text-zinc-500 transition hover:bg-white hover:text-purple-700"
                              :aria-expanded="isSourceExpanded(msg.id, source, sourceIndex)"
                              :aria-label="
                                isSourceExpanded(msg.id, source, sourceIndex)
                                  ? '收起此参考内容'
                                  : '展开此参考内容'
                              "
                              :title="
                                isSourceExpanded(msg.id, source, sourceIndex)
                                  ? '收起内容'
                                  : '展开内容'
                              "
                              @click="toggleSource(msg.id, source, sourceIndex)"
                            >
                              <span>{{
                                isSourceExpanded(msg.id, source, sourceIndex) ? '收起' : '展开'
                              }}</span>
                              <ChevronDown
                                class="h-4 w-4 transition-transform"
                                :class="
                                  isSourceExpanded(msg.id, source, sourceIndex) ? 'rotate-180' : ''
                                "
                              />
                            </button>
                          </div>
                          <div
                            v-if="isSourceExpanded(msg.id, source, sourceIndex)"
                            class="mt-2 border-t border-zinc-200/70 pt-2 text-zinc-600"
                          >
                            <MarkdownRenderer :content="source.content || ''" />
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div
                    class="flex items-center gap-1 opacity-100 transition md:opacity-0 md:group-hover:opacity-100"
                  >
                    <template v-if="msg.role === 'user'">
                      <button
                        class="rounded-md p-1.5 text-zinc-400 hover:bg-white hover:text-purple-600 disabled:opacity-40"
                        title="编辑提问"
                        aria-label="编辑提问"
                        :disabled="chatStore.isSending"
                        @click="beginEdit(msg)"
                      >
                        <Pencil class="h-3.5 w-3.5" />
                      </button>
                    </template>
                    <template v-else>
                      <button
                        class="rounded-md p-1.5 text-zinc-400 hover:bg-white hover:text-purple-600 disabled:opacity-40"
                        title="复制回答"
                        aria-label="复制回答"
                        :disabled="!msg.content"
                        @click="copyAnswer(msg)"
                      >
                        <Check
                          v-if="copiedMessageId === msg.id"
                          class="h-3.5 w-3.5 text-emerald-600"
                        />
                        <Copy v-else class="h-3.5 w-3.5" />
                      </button>
                      <button
                        class="rounded-md p-1.5 text-zinc-400 hover:bg-white hover:text-purple-600 disabled:opacity-40"
                        :title="
                          msg.status === 'failed' ||
                          msg.status === 'interrupted' ||
                          msg.status === 'stopped'
                            ? '重试回答'
                            : '重新生成回答'
                        "
                        aria-label="重新生成回答"
                        :disabled="chatStore.isSending"
                        @click="chatStore.regenerateMessage(msg.id)"
                      >
                        <RefreshCw class="h-3.5 w-3.5" />
                      </button>
                    </template>
                    <span
                      v-if="msg.role === 'assistant' && msg.status === 'completed'"
                      class="ml-1 text-[10px] text-zinc-300"
                    >
                      {{ index + 1 }}
                    </span>
                  </div>
                </div>
              </div>
            </template>

            <div v-else class="flex flex-col items-center justify-center px-4 py-20 text-center">
              <div
                class="mb-6 flex h-16 w-16 items-center justify-center rounded-2xl border border-zinc-200 bg-white shadow-sm"
              >
                <Bot class="h-8 w-8 text-purple-600" />
              </div>
              <h3 class="mb-2 text-xl font-bold text-zinc-800">欢迎来到 Second Brain</h3>
              <p class="max-w-sm leading-relaxed text-zinc-500">
                询问你已保存的知识，回答会附上相关文档来源。
              </p>
            </div>
          </div>
        </main>

        <footer
          class="shrink-0 bg-gradient-to-t from-zinc-50 via-zinc-50 to-transparent px-4 pb-4 pt-3 md:px-6 md:pb-6"
        >
          <div class="group relative mx-auto max-w-4xl">
            <div
              class="absolute -inset-1 rounded-2xl bg-gradient-to-r from-purple-400 to-purple-600 opacity-10 blur transition duration-500 group-focus-within:opacity-20"
            />
            <div
              class="relative flex items-end gap-3 rounded-2xl border border-zinc-200 bg-white p-3 shadow-xl"
            >
              <textarea
                ref="textareaRef"
                v-model="inputContent"
                rows="1"
                placeholder="输入你的问题…"
                class="max-h-52 min-h-[44px] flex-1 resize-none overflow-y-auto border-none bg-transparent px-3 py-2 leading-6 text-zinc-800 placeholder-zinc-400 focus:outline-none"
                @keydown="handleKeydown"
                @input="autoResize"
              />
              <button
                v-if="chatStore.isSending"
                class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-zinc-800 text-white transition hover:bg-zinc-700"
                title="停止生成"
                aria-label="停止生成"
                @click="chatStore.stopGeneration"
              >
                <Square class="h-4 w-4 fill-current" />
              </button>
              <button
                v-else
                class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-purple-600 text-white shadow-lg shadow-purple-600/20 transition hover:bg-purple-500 active:scale-95 disabled:cursor-not-allowed disabled:opacity-50"
                :disabled="!inputContent.trim()"
                title="发送消息"
                aria-label="发送消息"
                @click="handleSend"
              >
                <Send class="h-5 w-5" />
              </button>
            </div>
            <p class="mt-2 text-center text-[10px] text-zinc-400">
              按 Enter 发送，按 Shift + Enter 换行 · 内容仅基于当前知识库
            </p>
          </div>
        </footer>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref } from 'vue'
import {
  BookOpen,
  Bot,
  Check,
  ChevronDown,
  Copy,
  FileText,
  PanelLeft,
  Pencil,
  Plus,
  RefreshCw,
  Send,
  Square,
  Trash2,
  User,
} from 'lucide-vue-next'
import { useChatStore } from '@/stores/chat'
import type { ChatMessage } from '@/api/chat'
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'

const chatStore = useChatStore()
const inputContent = ref('')
const editingMessageId = ref<string | null>(null)
const editingContent = ref('')
const copiedMessageId = ref<string | null>(null)
const expandedSources = ref(new Set<string>())
const sidebarOpen = ref(true)
const scrollContainer = ref<HTMLElement | null>(null)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
// 是否跳过下一次自动滚动
const skipAutoScroll = ref(false)
let observer: MutationObserver | null = null
let copiedTimeout: ReturnType<typeof setTimeout> | undefined

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && event.shiftKey) return
  if (event.key === 'Enter') {
    event.preventDefault()
    void handleSend()
  }
}

function autoResize() {
  const textarea = textareaRef.value
  if (!textarea) return
  textarea.style.height = 'auto'
  textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`
}

async function handleSend() {
  if (!inputContent.value.trim() || chatStore.isSending) return
  const content = inputContent.value
  inputContent.value = ''
  await nextTick()
  if (textareaRef.value) textareaRef.value.style.height = '44px'
  await chatStore.sendMessage(content)
}

async function newConversation() {
  try {
    await chatStore.startNewConversation()
    sidebarOpen.value = false
  } catch (error) {
    window.alert(error instanceof Error ? error.message : '新建会话失败')
  }
}

async function openConversation(id: string) {
  await chatStore.selectConversation(id)
  sidebarOpen.value = false
}

async function renameConversation(id: string, currentTitle: string) {
  const title = window.prompt('输入新的会话名称', currentTitle)
  if (title === null || !title.trim()) return
  try {
    await chatStore.renameConversation(id, title)
  } catch (error) {
    window.alert(error instanceof Error ? error.message : '重命名失败')
  }
}

async function deleteConversation(id: string) {
  const conversation = chatStore.conversations.find((item) => item.id === id)
  const title = conversation?.title || '这个会话'
  if (!window.confirm(`确定删除“${title}”及其中的全部消息吗？此操作无法撤销。`)) return
  try {
    await chatStore.removeConversation(id)
  } catch (error) {
    window.alert(error instanceof Error ? error.message : '删除会话失败')
  }
}

function beginEdit(message: ChatMessage) {
  editingMessageId.value = message.id
  editingContent.value = message.content
}

function sourceKey(
  messageId: string,
  source: NonNullable<ChatMessage['sources']>[number],
  index: number,
) {
  return `${messageId}:${source.id || `${source.filename || 'source'}:${index}`}`
}

function isSourceExpanded(
  messageId: string,
  source: NonNullable<ChatMessage['sources']>[number],
  index: number,
) {
  return expandedSources.value.has(sourceKey(messageId, source, index))
}

async function toggleSource(
  messageId: string,
  source: NonNullable<ChatMessage['sources']>[number],
  index: number,
) {
  // 本次操作禁止自动滚动
  skipAutoScroll.value = true

  const next = new Set(expandedSources.value)
  const key = sourceKey(messageId, source, index)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expandedSources.value = next

  // 等待 Vue 完成 DOM 更新后恢复自动滚动
  await nextTick()
  skipAutoScroll.value = false
}

function cancelEdit() {
  editingMessageId.value = null
  editingContent.value = ''
}

async function saveEdit(messageId: string) {
  if (!editingContent.value.trim()) return
  await chatStore.editMessage(messageId, editingContent.value)
  cancelEdit()
}

async function copyAnswer(message: ChatMessage) {
  if (!message.content) return
  try {
    await navigator.clipboard.writeText(message.content)
    copiedMessageId.value = message.id
    if (copiedTimeout) clearTimeout(copiedTimeout)
    copiedTimeout = setTimeout(() => {
      copiedMessageId.value = null
    }, 1500)
  } catch {
    window.alert('复制失败，请检查浏览器剪贴板权限。')
  }
}

function scrollToBottom(behavior: ScrollBehavior = 'smooth') {
  scrollContainer.value?.scrollTo({
    top: scrollContainer.value.scrollHeight,
    behavior,
  })
}

onMounted(async () => {
  sidebarOpen.value = window.matchMedia('(min-width: 768px)').matches
  await chatStore.initialize()
  await nextTick()
  scrollToBottom('auto')
  if (scrollContainer.value) {
    observer = new MutationObserver(() => {
      if (skipAutoScroll.value) return
      scrollToBottom('smooth')
    })
    observer.observe(scrollContainer.value, {
      childList: true,
      subtree: true,
      characterData: true,
    })
  }
})

onUnmounted(() => {
  observer?.disconnect()
  if (copiedTimeout) clearTimeout(copiedTimeout)
  void chatStore.stopGeneration()
})
</script>

<style scoped>
.conversation-row {
  display: flex;
  align-items: center;
  min-height: 2.5rem;
  border-radius: 0.625rem;
  color: #52525b;
  transition:
    background-color 0.15s ease,
    color 0.15s ease;
}

.conversation-row:hover {
  background: #f4f4f5;
}

.conversation-row-active {
  background: #f5f3ff;
  color: #6d28d9;
}

.conversation-actions {
  opacity: 0.65;
}

.conversation-row:hover .conversation-actions,
.conversation-row-active .conversation-actions {
  opacity: 1;
}

::-webkit-scrollbar {
  width: 6px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: #d4d4d8;
}

::-webkit-scrollbar-thumb:hover {
  background: #a1a1aa;
}
</style>
