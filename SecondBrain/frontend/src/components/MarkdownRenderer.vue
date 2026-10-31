<script setup lang="ts">
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'
import 'highlight.js/styles/atom-one-dark.css'

const props = defineProps<{
  content: string
}>()

const md = new MarkdownIt({
  html: true,
  linkify: true,
  typographer: true,
  highlight: function (str, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return `<pre class="hljs"><code>${
          hljs.highlight(str, { language: lang, ignoreIllegals: true }).value
        }</code></pre>`
      } catch (__) {}
    }
    return `<pre class="hljs"><code>${md.utils.escapeHtml(str)}</code></pre>`
  },
})

const renderedHtml = computed(() => {
  return md.render(props.content || '')
})
</script>

<template>
  <div
    class="markdown-body prose prose-slate dark:prose-invert max-w-none min-w-0 w-full prose-pre:bg-zinc-900 prose-pre:border prose-pre:border-zinc-800"
    v-html="renderedHtml"
  ></div>
</template>

<style>
/* Markdown 容器不能被内部内容撑宽 */
.markdown-body {
  width: 100%;
  min-width: 0;
  max-width: 100%;
  overflow-wrap: anywhere;
}

/* 代码块限制最大宽度，横向滚动只发生在代码块内部 */
.markdown-body pre {
  @apply rounded-xl p-4 my-4 overflow-x-auto;
  max-width: 100%;
  min-width: 0;
  box-sizing: border-box;
  white-space: pre;
}

/* 保留代码原始格式，不让代码内容撑开父容器 */
.markdown-body pre code {
  display: block;
  width: max-content;
  min-width: 100%;
  max-width: none;
  white-space: pre;
}

/* 行内代码允许必要时换行 */
.markdown-body :not(pre) > code {
  overflow-wrap: anywhere;
  white-space: break-spaces;
}

.markdown-body p {
  @apply leading-relaxed mb-4 last:mb-0;
}

.markdown-body a {
  @apply text-purple-400 hover:text-purple-300 transition-colors;
  overflow-wrap: anywhere;
}

.markdown-body ul,
.markdown-body ol {
  @apply my-4 pl-6;
}

.markdown-body li {
  @apply mb-2;
}

/* 表格过宽时允许局部滚动 */
.markdown-body table {
  display: block;
  max-width: 100%;
  overflow-x: auto;
}
</style>
