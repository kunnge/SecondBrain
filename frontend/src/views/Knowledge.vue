<template>
  <Toast :visible="toast.visible" :message="toast.message" :type="toast.type" />

  <div class="knowledge-page flex min-h-0 flex-1 flex-col text-zinc-900">
    <header
      class="knowledge-header flex min-h-[72px] items-center justify-between border-b border-zinc-200/80 bg-white/95 px-8"
    >
      <div class="min-w-0">
        <div
          class="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-purple-500"
        >
          <span class="h-1.5 w-1.5 rounded-full bg-purple-500"></span>Second Brain
        </div>
        <div class="mt-1 flex items-baseline gap-3">
          <h2 class="text-xl font-semibold tracking-tight text-zinc-900">知识库管理</h2>
          <p class="hidden text-sm text-zinc-500 sm:block">整理文档与 AI 元数据</p>
        </div>
      </div>
      <div class="flex shrink-0 flex-wrap items-center justify-end gap-2">
        <button class="action" :disabled="syncActive" @click="startSync">
          <RefreshCw class="h-4 w-4" :class="{ 'animate-spin': syncActive }" />
          {{ syncActive ? '正在同步 Obsidian...' : '同步 Obsidian' }}
        </button>
        <button class="action primary" :disabled="uploading" @click="fileInput?.click()">
          <Upload class="h-4 w-4" />{{ uploading ? '正在处理文档...' : '上传 Markdown' }}
        </button>
      </div>
      <input
        ref="fileInput"
        type="file"
        accept=".md,text/markdown"
        class="hidden"
        @change="selectFile"
      />
    </header>

    <main class="knowledge-main min-h-0 flex-1 overflow-y-auto px-8 py-7">
      <div v-if="selected" class="mx-auto max-w-[1320px] space-y-5">
        <button class="back" @click="closeDetail"><ArrowLeft class="h-4 w-4" />返回知识列表</button>
        <div class="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
          <section class="panel min-w-0">
            <div class="border-b border-zinc-100 p-6">
              <div class="flex flex-wrap items-start justify-between gap-4">
                <div class="min-w-0">
                  <p class="mb-2 text-xs text-zinc-400">{{ selected.filename }}</p>
                  <h1 class="break-words text-2xl font-semibold">
                    {{ selected.title || selected.filename }}
                  </h1>
                </div>
              </div>
              <div class="mt-4 flex flex-wrap items-center gap-2 text-xs">
                <span :class="statusClass(selected.processing_status)"
                  >索引{{ statusLabel(selected.processing_status) }}</span
                >
                <span :class="statusClass(selected.metadata_status)"
                  >AI 元数据{{ statusLabel(selected.metadata_status) }}</span
                >
              </div>
              <p
                v-if="selected.metadata_error"
                class="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800"
              >
                {{ selected.metadata_error }}
              </p>
              <p class="mt-4 text-sm leading-6 text-zinc-500">
                {{ selected.summary || '暂无摘要' }}
              </p>
            </div>

            <div
              class="border-b border-zinc-100 px-6 py-3 text-xs font-semibold uppercase tracking-wider text-zinc-400"
            >
              Markdown 原文
            </div>
            <div v-if="detailLoading" class="space-y-3 p-6">
              <div class="h-4 w-3/4 animate-pulse rounded bg-zinc-100"></div>
              <div class="h-4 w-full animate-pulse rounded bg-zinc-100"></div>
              <div class="h-4 w-5/6 animate-pulse rounded bg-zinc-100"></div>
            </div>
            <div v-else class="max-h-[60vh] overflow-auto p-6 text-sm leading-7 text-zinc-700">
              <MarkdownRenderer :content="selected.content || '暂无 Markdown 内容'" />
            </div>
          </section>

          <aside class="panel h-fit p-5">
            <div class="mb-5 flex items-center justify-between">
              <h3 class="font-semibold">文档信息</h3>
              <span class="text-xs text-zinc-400">{{ date(selected.created_at) }}</span>
            </div>
            <div class="space-y-4">
              <label>标题<input v-model="form.title" class="field" maxlength="255" /></label>
              <label
                >摘要<textarea v-model="form.summary" class="field min-h-24 resize-y" rows="3" />
              </label>
              <label>
                分类
                <input
                  v-model="form.category"
                  class="field"
                  list="knowledge-category-options"
                  maxlength="100"
                  placeholder="输入或选择分类"
                  autocomplete="off"
                />
                <datalist id="knowledge-category-options">
                  <option v-for="item in categoriesForEdit" :key="item" :value="item" />
                </datalist>
                <small class="mt-1 block font-normal text-zinc-400"
                  >可选择已有分类，也可输入新分类；留空会保存为“未分类”。</small
                >
              </label>
              <label
                >标签<input v-model="form.tags" class="field" placeholder="用逗号分隔标签"
              /></label>
              <label
                >关键词<input v-model="form.keywords" class="field" placeholder="用逗号分隔关键词"
              /></label>
              <button class="action primary w-full justify-center" :disabled="saving" @click="save">
                {{ saving ? '保存中...' : '保存修改' }}
              </button>
            </div>
          </aside>
        </div>
      </div>

      <div v-else class="knowledge-content mx-auto max-w-[1320px] space-y-5">
        <section class="intro-panel">
          <div>
            <span class="section-kicker">PERSONAL KNOWLEDGE OS</span>
            <h1>把重要内容，放在随时可用的地方</h1>
            <p>上传 Markdown 文档，Second Brain 会为你整理摘要、分类和标签。</p>
          </div>
          <div class="intro-stats">
            <div>
              <strong>{{ total }}</strong
              ><span>文档总数</span>
            </div>
            <div>
              <strong>{{ tags.length }}</strong
              ><span>标签</span>
            </div>
            <div>
              <strong>{{ categories.length - 1 }}</strong
              ><span>分类</span>
            </div>
          </div>
        </section>

        <section v-if="syncJob" class="panel space-y-3 p-5" aria-live="polite">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 class="font-semibold">Obsidian 同步</h3>
              <p class="mt-1 text-xs text-zinc-500">
                {{ syncStatusLabel(syncJob.status) }}<span v-if="syncJob.current_file"> · {{ syncJob.current_file }}</span>
              </p>
            </div>
            <span :class="statusClass(syncJob.status === 'queued' ? 'pending' : syncJob.status === 'running' ? 'processing' : syncJob.status === 'completed' ? 'completed' : 'failed')">
              {{ syncStatusLabel(syncJob.status) }}
            </span>
          </div>
          <div class="grid grid-cols-2 gap-3 text-sm sm:grid-cols-6">
            <div><strong>{{ syncJob.scanned_count }}</strong><small class="ml-1 text-zinc-500">扫描</small></div>
            <div><strong>{{ syncJob.added_count }}</strong><small class="ml-1 text-zinc-500">新增</small></div>
            <div><strong>{{ syncJob.updated_count }}</strong><small class="ml-1 text-zinc-500">更新</small></div>
            <div><strong>{{ syncJob.skipped_count }}</strong><small class="ml-1 text-zinc-500">跳过</small></div>
            <div><strong>{{ syncJob.deleted_count }}</strong><small class="ml-1 text-zinc-500">删除</small></div>
            <div><strong>{{ syncJob.failed_count }}</strong><small class="ml-1 text-zinc-500">失败</small></div>
          </div>
          <ul v-if="syncJob.errors.length" class="max-h-36 space-y-1 overflow-auto rounded-lg bg-amber-50 p-3 text-xs text-amber-800">
            <li v-for="(item, index) in syncJob.errors" :key="`${item.path}-${index}`">
              <strong>{{ item.path || '任务' }}：</strong>{{ item.error }}
            </li>
          </ul>
        </section>

        <section class="toolbar-panel">
          <div class="toolbar-title">
            <div class="toolbar-icon"><Search class="h-4 w-4" /></div>
            <div>
              <h3>查找知识</h3>
              <p>按标题、摘要、分类或标签快速定位</p>
            </div>
          </div>
          <div class="toolbar-fields">
            <label class="relative min-w-0 flex-1">
              <Search
                class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400"
              />
              <input v-model="query" class="field" placeholder="搜索标题、摘要或关键词" />
            </label>
            <select v-model="category" class="field lg:w-44">
              <option value="">全部分类</option>
              <option v-for="item in categories" :key="item" :value="item">{{ item }}</option>
            </select>
            <select v-model="tag" class="field lg:w-44">
              <option value="">全部标签</option>
              <option v-for="item in tags" :key="item" :value="item">{{ item }}</option>
            </select>
            <button class="action" @click="reset"><RotateCcw class="h-4 w-4" />重置</button>
          </div>
        </section>

        <section class="panel document-panel overflow-hidden">
          <div class="flex items-center justify-between border-b border-zinc-100 px-6 py-5">
            <div>
              <div class="flex items-center gap-2">
                <h3 class="text-base font-semibold">知识文档</h3>
                <span class="count-badge">{{ total }}</span>
              </div>
              <p class="mt-1 text-xs text-zinc-500">点击文档查看详情、编辑元数据</p>
            </div>
            <button class="icon-button" title="刷新列表" :disabled="loading" @click="fetchDocs">
              <RefreshCw class="h-4 w-4" :class="{ 'animate-spin': loading }" />
            </button>
          </div>

          <div v-if="loading" class="space-y-3 p-6">
            <div v-for="i in 5" :key="i" class="h-14 animate-pulse rounded-lg bg-zinc-100" />
          </div>
          <div v-else-if="loadError" class="empty">
            <div class="empty-icon"><AlertCircle class="h-6 w-6" /></div>
            <p>暂时无法加载知识库</p>
            <small>{{ loadError }}</small
            ><button class="action mt-5" @click="fetchDocs">
              <RefreshCw class="h-4 w-4" />重试
            </button>
          </div>
          <div v-else-if="docs.length" class="overflow-x-auto">
            <div class="min-w-[850px]">
              <div class="table-row header">
                <span>文档</span><span>分类</span><span>标签</span><span>处理状态</span
                ><span>上传时间</span>
              </div>
              <button
                v-for="doc in docs"
                :key="doc.id"
                class="table-row body w-full text-left"
                @click="open(doc)"
              >
                <span class="min-w-0"
                  ><span class="flex items-center gap-3"
                    ><span class="file-icon"><FileText class="h-4 w-4" /></span
                    ><span class="min-w-0"
                      ><strong class="block truncate">{{ doc.title || doc.filename }}</strong
                      ><small class="mt-1 block truncate">{{
                        doc.summary || doc.filename
                      }}</small></span
                    ></span
                  ></span
                >
                <span
                  ><span class="category-badge">{{ doc.category || '未分类' }}</span></span
                >
                <span class="flex flex-wrap gap-1"
                  ><em v-for="item in doc.tags.slice(0, 3)" :key="item">{{ item }}</em
                  ><small v-if="!doc.tags.length">暂无标签</small></span
                >
                <span class="flex flex-col items-start gap-1"
                  ><span :class="statusClass(doc.processing_status)">{{
                    statusLabel(doc.processing_status)
                  }}</span
                  ><span v-if="doc.metadata_status === 'failed'" class="text-[10px] text-amber-700"
                    >元数据失败</span
                  ></span
                >
                <span class="date-cell">{{ date(doc.created_at) }}</span>
              </button>
            </div>
          </div>
          <div v-else class="empty">
            <div class="empty-icon"><Upload class="h-6 w-6" /></div>
            <p>从第一篇知识开始</p>
            <small>上传 Markdown 文档后，它会出现在这里</small
            ><button class="action primary mt-5" @click="fileInput?.click()">
              <Upload class="h-4 w-4" />上传第一篇文档
            </button>
          </div>

          <div
            v-if="!loading && !loadError && pages > 1"
            class="flex items-center justify-between border-t border-zinc-100 px-6 py-3"
          >
            <small>第 {{ current }} / {{ pages }} 页，共 {{ total }} 个文档</small>
            <div class="flex gap-1">
              <button class="page" :disabled="current === 1" @click="current--">
                <ChevronLeft class="h-4 w-4" /></button
              ><button
                v-for="n in pages"
                :key="n"
                class="page"
                :class="{ active: n === current }"
                @click="current = n"
              >
                {{ n }}</button
              ><button class="page" :disabled="current === pages" @click="current++">
                <ChevronRight class="h-4 w-4" />
              </button>
            </div>
          </div>
        </section>
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import {
  AlertCircle,
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  FileText,
  RefreshCw,
  RotateCcw,
  Search,
  Upload,
} from 'lucide-vue-next'
import Toast from '@/components/Toast.vue'
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'
import { getDocument, listDocuments, updateDocument, type KnowledgeDocument } from '@/api/knowledge'
import { uploadMarkdown } from '@/api/chat'
import { getObsidianSync, startObsidianSync, type ObsidianSyncJob } from '@/api/obsidian'

const docs = ref<KnowledgeDocument[]>([])
const selected = ref<KnowledgeDocument | null>(null)
const loading = ref(true)
const detailLoading = ref(false)
const uploading = ref(false)
const syncJob = ref<ObsidianSyncJob | null>(null)
const syncActive = computed(() => syncJob.value?.status === 'queued' || syncJob.value?.status === 'running')
const saving = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const query = ref('')
const category = ref('')
const tag = ref('')
const current = ref(1)
const pageSize = 8
const total = ref(0)
const pages = ref(1)
const categories = ref<string[]>([])
const tags = ref<string[]>([])
const loadError = ref('')
const form = reactive({ title: '', summary: '', category: '未分类', tags: '', keywords: '' })
const toast = reactive({ visible: false, message: '', type: 'success' as 'success' | 'error' })
const categoriesForEdit = computed(() =>
  [...new Set([...categories.value, form.category || '未分类'])].filter(Boolean),
)
let toastTimer: ReturnType<typeof setTimeout> | undefined
let searchTimer: ReturnType<typeof setTimeout> | undefined
let syncTimer: ReturnType<typeof setInterval> | undefined
let syncRequestPending = false

const message = (text: string, type: 'success' | 'error' = 'success') => {
  toast.message = text
  toast.type = type
  toast.visible = true
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => {
    toast.visible = false
  }, 3200)
}
const errorText = (error: unknown) =>
  error instanceof Error ? error.message : '请求失败，请稍后重试'
const statusLabel = (
  status: KnowledgeDocument['processing_status'] | KnowledgeDocument['metadata_status'],
) =>
  ({ pending: '等待处理', processing: '处理中', completed: '已完成', failed: '处理失败' })[
    status
  ] || '未知状态'
const statusClass = (
  status: KnowledgeDocument['processing_status'] | KnowledgeDocument['metadata_status'],
) =>
  ({
    pending: 'status-badge pending',
    processing: 'status-badge processing',
    completed: 'status-badge completed',
    failed: 'status-badge failed',
  })[status]
const syncStatusLabel = (status: ObsidianSyncJob['status']) =>
  ({ queued: '等待开始', running: '同步进行中', completed: '同步完成', failed: '同步失败' })[status]
const date = (value: string) => {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '未知时间' : parsed.toLocaleDateString('zh-CN')
}

async function fetchDocs() {
  loading.value = true
  loadError.value = ''
  try {
    const result = await listDocuments({
      q: query.value.trim() || undefined,
      category: category.value || undefined,
      tag: tag.value || undefined,
      page: current.value,
      page_size: pageSize,
    })
    docs.value = result.items
    total.value = result.total
    pages.value = Math.max(1, result.total_pages)
    categories.value = result.categories || []
    tags.value = result.tags || []
    if (current.value > pages.value) current.value = pages.value
  } catch (error) {
    docs.value = []
    total.value = 0
    loadError.value = errorText(error)
  } finally {
    loading.value = false
  }
}

function scheduleFetch() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    void fetchDocs()
  }, 250)
}

watch([query, category, tag], () => {
  current.value = 1
  scheduleFetch()
})
watch(current, scheduleFetch)

function reset() {
  query.value = ''
  category.value = ''
  tag.value = ''
  current.value = 1
}

function fillForm(doc: KnowledgeDocument) {
  form.title = doc.title || doc.filename
  form.summary = doc.summary || ''
  form.category = doc.category || '未分类'
  form.tags = (doc.tags || []).join(', ')
  form.keywords = (doc.keywords || []).join(', ')
}

async function open(doc: KnowledgeDocument) {
  selected.value = doc
  fillForm(doc)
  detailLoading.value = true
  try {
    selected.value = await getDocument(doc.id)
    fillForm(selected.value)
  } catch (error) {
    message(`获取文档详情失败：${errorText(error)}`, 'error')
  } finally {
    detailLoading.value = false
  }
}

function closeDetail() {
  selected.value = null
  void fetchDocs()
}

async function save() {
  if (!selected.value) return
  saving.value = true
  try {
    selected.value = await updateDocument(selected.value.id, {
      title: form.title.trim() || selected.value.filename,
      summary: form.summary.trim(),
      category: form.category.trim() || '未分类',
      tags: form.tags
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean),
      keywords: form.keywords
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean),
    })
    fillForm(selected.value)
    message('文档信息已保存')
  } catch (error) {
    message(`保存失败：${errorText(error)}`, 'error')
  } finally {
    saving.value = false
  }
}

async function selectFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  if (!file.name.toLowerCase().endsWith('.md')) {
    message('仅支持上传 Markdown 文件', 'error')
    input.value = ''
    return
  }
  uploading.value = true
  try {
    const result = await uploadMarkdown(file)
    message(
      result.metadata_status === 'failed'
        ? '文档已入库，但 AI 元数据生成失败，可在详情中手动补充'
        : '文档已上传并完成处理',
      result.metadata_status === 'failed' ? 'error' : 'success',
    )
    await fetchDocs()
  } catch (error) {
    message(`上传处理失败：${errorText(error)}`, 'error')
    await fetchDocs()
  } finally {
    uploading.value = false
    input.value = ''
  }
}

function stopSyncPolling() {
  if (syncTimer) clearInterval(syncTimer)
  syncTimer = undefined
}

async function refreshSyncStatus(taskId: string) {
  if (syncRequestPending) return
  syncRequestPending = true
  try {
    const result = await getObsidianSync(taskId)
    syncJob.value = result
    if (!['queued', 'running'].includes(result.status)) {
      stopSyncPolling()
      if (result.status === 'completed') await fetchDocs()
    }
  } catch (error) {
    stopSyncPolling()
    message(`获取 Obsidian 同步状态失败：${errorText(error)}`, 'error')
  } finally {
    syncRequestPending = false
  }
}

function watchSync(taskId: string) {
  localStorage.setItem('obsidianSyncTaskId', taskId)
  stopSyncPolling()
  syncTimer = setInterval(() => void refreshSyncStatus(taskId), 1500)
  void refreshSyncStatus(taskId)
}

async function startSync() {
  if (syncActive.value) return
  try {
    const job = await startObsidianSync()
    syncJob.value = job
    watchSync(job.id)
    message('已启动 Obsidian Vault 同步')
  } catch (error) {
    message(`启动 Obsidian 同步失败：${errorText(error)}`, 'error')
  }
}

onMounted(() => {
  void fetchDocs()
  const taskId = localStorage.getItem('obsidianSyncTaskId')
  if (taskId) watchSync(taskId)
})
onUnmounted(() => {
  if (toastTimer) clearTimeout(toastTimer)
  if (searchTimer) clearTimeout(searchTimer)
  stopSyncPolling()
})
</script>

<style scoped>
.knowledge-page {
  background: #f8f7fc;
}
.knowledge-header {
  box-shadow: 0 1px 0 rgb(24 24 27/0.02);
}
.knowledge-main {
  background: #f8f7fc;
}
.panel {
  border: 1px solid rgb(228 228 231);
  border-radius: 0.875rem;
  background: #fff;
  box-shadow: 0 8px 24px rgb(39 16 76/0.035);
}
.intro-panel {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 2rem;
  border: 1px solid rgb(221 207 244);
  border-radius: 0.875rem;
  background: #f4effd;
  padding: 1.5rem 1.75rem;
  box-shadow: 0 8px 20px rgb(100 50 160/0.05);
}
.section-kicker {
  font-size: 0.67rem;
  font-weight: 700;
  letter-spacing: 0.18em;
  color: #8b5cf6;
}
.intro-panel h1 {
  margin-top: 0.45rem;
  font-size: 1.45rem;
  line-height: 1.25;
  font-weight: 650;
  letter-spacing: -0.02em;
  color: #312e3b;
}
.intro-panel p {
  margin-top: 0.5rem;
  font-size: 0.875rem;
  color: #71677f;
}
.intro-stats {
  display: flex;
  flex-shrink: 0;
  gap: 1.75rem;
  border-left: 1px solid rgb(139 92 246/0.2);
  padding-left: 1.75rem;
}
.intro-stats div {
  display: flex;
  min-width: 4rem;
  flex-direction: column;
  gap: 0.2rem;
}
.intro-stats strong {
  font-size: 1.3rem;
  line-height: 1;
  color: #6d28d9;
}
.intro-stats span {
  font-size: 0.7rem;
  color: #8b8198;
}
.toolbar-panel {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 2rem;
  border: 1px solid rgb(228 228 231);
  border-radius: 0.875rem;
  background: #fff;
  padding: 1rem 1.25rem;
  box-shadow: 0 4px 12px rgb(24 24 27/0.025);
}
.toolbar-title {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-shrink: 0;
}
.toolbar-icon {
  display: flex;
  height: 2.25rem;
  width: 2.25rem;
  align-items: center;
  justify-content: center;
  border-radius: 0.625rem;
  background: #f4effd;
  color: #7c3aed;
}
.toolbar-title h3 {
  font-size: 0.875rem;
  font-weight: 650;
  color: #3f3f46;
}
.toolbar-title p {
  margin-top: 0.15rem;
  font-size: 0.72rem;
  color: #a1a1aa;
}
.toolbar-fields {
  display: flex;
  min-width: 0;
  flex: 1;
  align-items: center;
  gap: 0.625rem;
  justify-content: flex-end;
}
.toolbar-fields > label {
  min-width: 18rem;
}
.toolbar-fields > select.field {
  width: 11rem;
  flex: 0 0 11rem;
}
.field {
  width: 100%;
  border: 1px solid rgb(228 228 231);
  border-radius: 0.5rem;
  background: #fff;
  padding: 0.625rem 2rem;
  font-size: 0.875rem;
  outline: 0;
  display: block;
  margin-top: 0.35rem;
  color: #3f3f46;
}
.toolbar-fields .field {
  margin-top: 0;
  height: 2.5rem;
}
.field:focus {
  border-color: #a855f7;
  box-shadow: 0 0 0 3px rgb(168 85 247/0.12);
}
label {
  display: block;
  font-size: 0.75rem;
  font-weight: 500;
  color: #71717a;
}
.action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  border: 1px solid rgb(228 228 231);
  border-radius: 0.5rem;
  padding: 0.625rem 0.875rem;
  font-size: 0.875rem;
  font-weight: 500;
  color: #3f3f46;
  background: #fff;
  white-space: nowrap;
  transition:
    background 0.15s,
    border-color 0.15s,
    color 0.15s,
    transform 0.15s;
}
.action:hover {
  background: #fafafa;
  border-color: #d4d4d8;
}
.action:active {
  transform: translateY(1px);
}
.action.primary {
  color: #fff;
  background: #7c3aed;
  border-color: #7c3aed;
  box-shadow: 0 5px 12px rgb(124 58 237/0.2);
}
.action.primary:hover {
  background: #6d28d9;
  border-color: #6d28d9;
}
.action:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.back {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  color: #71717a;
  font-size: 0.875rem;
}
.back:hover {
  color: #7c3aed;
}
.icon-button {
  padding: 0.5rem;
  color: #a1a1aa;
  border-radius: 0.5rem;
}
.icon-button:hover {
  background: #f4f4f5;
  color: #3f3f46;
}
.icon-button:disabled {
  opacity: 0.5;
}
.count-badge {
  display: inline-flex;
  min-width: 1.5rem;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: #f4effd;
  padding: 0.2rem 0.45rem;
  font-size: 0.68rem;
  font-weight: 700;
  color: #7c3aed;
}
.table-row {
  display: grid;
  grid-template-columns: minmax(0, 2fr) 130px 190px 130px 120px;
  gap: 1rem;
  align-items: center;
  padding: 1rem 1.5rem;
  font-size: 0.875rem;
  color: #52525b;
}
.table-row.header {
  background: #fcfbfe;
  color: #a1a1aa;
  font-size: 0.68rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}
.table-row.body {
  border-bottom: 1px solid #f4f4f5;
  transition: background 0.15s;
}
.table-row.body:hover {
  background: #fbf8ff;
}
.table-row strong {
  font-weight: 600;
  color: #3f3f46;
}
.table-row small {
  font-size: 0.75rem;
  color: #71717a;
}
.date-cell {
  font-size: 0.75rem;
  color: #71717a;
}
.file-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 2.25rem;
  height: 2.25rem;
  border-radius: 0.625rem;
  background: #f4effd;
  color: #7c3aed;
  flex-shrink: 0;
}
.category-badge {
  display: inline-flex;
  border-radius: 0.375rem;
  background: #f7f7f8;
  padding: 0.32rem 0.55rem;
  font-size: 0.72rem;
  color: #52525b;
}
.table-row em {
  font-style: normal;
  border-radius: 0.375rem;
  background: #f4f4f5;
  padding: 0.25rem 0.5rem;
  font-size: 0.72rem;
  color: #52525b;
}
.status-badge {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 0.25rem 0.5rem;
  font-size: 0.65rem;
  font-weight: 600;
  white-space: nowrap;
}
.status-badge.pending {
  background: #f4f4f5;
  color: #71717a;
}
.status-badge.processing {
  background: #eff6ff;
  color: #2563eb;
}
.status-badge.completed {
  background: #ecfdf5;
  color: #047857;
}
.status-badge.failed {
  background: #fff7ed;
  color: #c2410c;
}
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 5rem 1.5rem;
  color: #a1a1aa;
}
.empty-icon {
  display: flex;
  height: 3rem;
  width: 3rem;
  align-items: center;
  justify-content: center;
  border-radius: 0.875rem;
  background: #f4effd;
  color: #8b5cf6;
}
.empty p {
  margin-top: 0.85rem;
  color: #3f3f46;
  font-size: 0.95rem;
  font-weight: 600;
}
.empty small {
  margin-top: 0.3rem;
  color: #a1a1aa;
  max-width: 36rem;
  text-align: center;
}
.page {
  display: inline-flex;
  min-width: 2rem;
  height: 2rem;
  align-items: center;
  justify-content: center;
  border-radius: 0.5rem;
  padding: 0.25rem 0.5rem;
  color: #52525b;
  font-size: 0.75rem;
}
.page:hover:not(:disabled) {
  background: #f4f4f5;
}
.page.active {
  background: #7c3aed;
  color: #fff;
}
.page:disabled {
  color: #d4d4d8;
  cursor: not-allowed;
}
@media (max-width: 1050px) {
  .knowledge-main {
    padding-left: 1.25rem;
    padding-right: 1.25rem;
  }
  .intro-panel,
  .toolbar-panel {
    align-items: flex-start;
    flex-direction: column;
  }
  .intro-stats {
    width: 100%;
    border-left: 0;
    border-top: 1px solid rgb(139 92 246/0.2);
    padding-left: 0;
    padding-top: 1rem;
  }
  .toolbar-fields {
    width: 100%;
    flex-wrap: wrap;
    justify-content: stretch;
  }
  .toolbar-fields > label {
    flex: 1 1 100%;
    min-width: 0;
  }
  .toolbar-fields > select.field {
    width: auto;
    flex: 1 1 10rem;
  }
  .toolbar-fields .action {
    height: 2.5rem;
  }
}
</style>
