<template>
  <Toast :visible="showToast" :message="toastMessage" :type="toastType" />

  <div class="flex-1 flex flex-col h-full bg-zinc-50 text-zinc-900">
    <header
      class="h-16 border-b border-zinc-200 flex items-center px-6 bg-white/80 backdrop-blur-md"
    >
      <h2 class="text-lg font-semibold tracking-tight text-zinc-800">知识库管理</h2>
    </header>

    <main class="flex-1 overflow-y-auto p-6">
      <div class="max-w-5xl mx-auto space-y-10 pb-20">
        <!-- 上传区域 -->
        <section
          class="relative group"
          @dragover.prevent="dragActive = true"
          @dragleave.prevent="dragActive = false"
          @drop.prevent="handleDrop"
        >
          <div
            class="border-2 border-dashed rounded-3xl p-12 text-center transition-all duration-300 cursor-pointer"
            :class="[
              dragActive
                ? 'border-purple-500 bg-purple-50 ring-4 ring-purple-100'
                : 'border-zinc-200 bg-white hover:border-purple-300 hover:bg-purple-50/30',
            ]"
            @click="fileInput?.click()"
          >
            <input
              ref="fileInput"
              type="file"
              class="hidden"
              accept=".md"
              @change="handleFileSelect"
            />

            <div class="flex flex-col items-center">
              <div
                class="w-16 h-16 rounded-2xl bg-zinc-50 flex items-center justify-center mb-6 group-hover:scale-110 transition-transform duration-300 shadow-sm"
                :class="{ 'animate-bounce': isUploading }"
              >
                <Upload
                  v-if="!isUploading"
                  class="w-8 h-8 text-zinc-400 group-hover:text-purple-600"
                />
                <Loader2 v-else class="w-8 h-8 text-purple-600 animate-spin" />
              </div>
              <h3 class="text-xl font-bold text-zinc-800 mb-2">
                {{ isUploading ? '正在上传并向量化...' : '上传知识文档' }}
              </h3>
              <p class="text-zinc-500 max-w-xs mx-auto leading-relaxed">
                点击或拖拽 Markdown 文件到此处，我们将自动完成解析与语义索引
              </p>
            </div>
          </div>
        </section>

        <!-- 文档列表 -->
        <section>
          <div class="flex items-center justify-between mb-6">
            <h3 class="text-sm font-medium text-zinc-400 uppercase tracking-widest">
              已上传文档资产
            </h3>
            <span class="text-xs text-zinc-400">{{ docs.length }} 个文件</span>
          </div>

          <!-- 加载状态 -->
          <div v-if="isLoading" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            <div
              v-for="i in 6"
              :key="i"
              class="p-5 bg-white rounded-2xl border border-zinc-100 animate-pulse shadow-sm"
            >
              <div class="flex items-start gap-4">
                <div class="w-10 h-10 bg-zinc-50 rounded-lg"></div>
                <div class="flex-1 space-y-2">
                  <div class="h-4 bg-zinc-50 rounded w-3/4"></div>
                  <div class="h-3 bg-zinc-50 rounded w-1/2"></div>
                </div>
              </div>
            </div>
          </div>

          <!-- 列表内容 -->
          <div
            v-else-if="docs.length > 0"
            class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4"
            v-auto-animate
          >
            <div
              v-for="doc in docs"
              :key="doc.id"
              class="group p-5 bg-white border border-zinc-200 rounded-2xl hover:border-purple-300 hover:shadow-lg hover:shadow-purple-500/5 transition-all duration-300 shadow-sm"
            >
              <div class="flex items-start justify-between">
                <div class="flex items-start gap-4">
                  <div
                    class="w-10 h-10 rounded-xl bg-zinc-50 flex items-center justify-center text-zinc-400 group-hover:bg-purple-50 group-hover:text-purple-600 transition-colors"
                  >
                    <FileText class="w-5 h-5" />
                  </div>
                  <div>
                    <h4
                      class="font-semibold text-zinc-800 truncate max-w-[150px]"
                      :title="doc.name"
                    >
                      {{ doc.name }}
                    </h4>
                    <p class="text-xs text-zinc-500 mt-1">{{ formatSize(doc.size) }}</p>
                  </div>
                </div>

                <div class="flex flex-col items-end gap-2">
                  <span
                    v-if="doc.status === 'parsing'"
                    class="flex items-center gap-1 text-[10px] text-amber-600 font-medium bg-amber-50 px-2 py-0.5 rounded-full border border-amber-100"
                  >
                    <Loader2 class="w-3 h-3 animate-spin" />
                    解析中
                  </span>
                  <span
                    v-else-if="doc.status === 'completed'"
                    class="flex items-center gap-1 text-[10px] text-emerald-600 font-medium bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-100"
                  >
                    <CheckCircle2 class="w-3 h-3" />
                    就绪
                  </span>
                  <span
                    v-else
                    class="flex items-center gap-1 text-[10px] text-rose-600 font-medium bg-rose-50 px-2 py-0.5 rounded-full border border-rose-100"
                  >
                    <AlertCircle class="w-3 h-3" />
                    失败
                  </span>
                </div>
              </div>

              <div
                class="mt-4 flex items-center justify-between opacity-0 group-hover:opacity-100 transition-opacity"
              >
                <span class="text-[10px] text-zinc-400"
                  >上传于 {{ new Date(doc.createdAt).toLocaleDateString() }}</span
                >
                <button
                  class="p-1.5 text-zinc-400 hover:text-rose-500 hover:bg-rose-50 rounded-lg transition-all"
                >
                  <Trash2 class="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>

          <!-- 空状态 -->
          <div
            v-else
            class="flex flex-col items-center justify-center py-20 bg-white rounded-3xl border border-zinc-200 border-dashed shadow-sm"
          >
            <div class="w-12 h-12 rounded-xl bg-zinc-50 flex items-center justify-center mb-4">
              <FileText class="w-6 h-6 text-zinc-300" />
            </div>
            <p class="text-zinc-400">暂无文档资产，请先上传</p>
          </div>
        </section>
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Upload, FileText, Trash2, Loader2, CheckCircle2, AlertCircle } from 'lucide-vue-next'
import axios from 'axios'
import { uploadMarkdown } from '@/api/chat'
import Toast from '@/components/Toast.vue'
interface Document {
  id: string
  name: string
  size: number
  status: 'parsing' | 'completed' | 'error'
  createdAt: string
}

const docs = ref<Document[]>([])
const isLoading = ref(true)
const isUploading = ref(false)
const dragActive = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

// 获取文档列表
const fetchDocs = async () => {
  isLoading.value = true
  try {
    const response = await axios.get('/api/docs')
    docs.value = response.data
  } catch (error) {
    showMessage(`获取文档失败: ${error}`, 'error')
  } finally {
    isLoading.value = false
  }
}

// 上传文件
const uploadFile = async (file: File) => {
  if (!file.name.endsWith('.md')) {
    showMessage('仅支持上传 Markdown 文件', 'error')
    return
  }

  isUploading.value = true

  try {
    const res = await uploadMarkdown(file)
    showMessage(res.message, 'success')
    await fetchDocs()
  } catch (error) {
    showMessage(error, 'error')
  } finally {
    isUploading.value = false
  }
}

// 处理拖拽
const handleDrop = (e: DragEvent) => {
  dragActive.value = false
  const files = e.dataTransfer?.files
  if (files && files.length > 0) {
    uploadFile(files[0])
  }
}

const handleFileSelect = (e: Event) => {
  const target = e.target as HTMLInputElement
  if (target.files && target.files.length > 0) {
    uploadFile(target.files[0])
  }
}

const formatSize = (bytes: number) => {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

onMounted(() => {
  fetchDocs()
})

// Toast提示框
const showToast = ref(false)
const toastMessage = ref('')
const toastType = ref<'success' | 'error'>('success')
const showMessage = (message: string, type: 'success' | 'error' = 'success') => {
  toastMessage.value = message

  toastType.value = type

  showToast.value = true

  setTimeout(() => {
    showToast.value = false
  }, 3000)
}
</script>

<style scoped>
/* 自定义滚动条 */
::-webkit-scrollbar {
  width: 6px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  @apply bg-zinc-200 rounded-full;
}

::-webkit-scrollbar-thumb:hover {
  @apply bg-zinc-300;
}
</style>
