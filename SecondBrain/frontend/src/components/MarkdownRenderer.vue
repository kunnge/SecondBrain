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
    class="markdown-body prose prose-slate dark:prose-invert max-w-none prose-pre:bg-zinc-900 prose-pre:border prose-pre:border-zinc-800"
    v-html="renderedHtml"
  ></div>
</template>

<style>
/* 自定义一些 markdown 样式以匹配 UI */
.markdown-body pre {
  @apply rounded-xl p-4 my-4 overflow-x-auto;
}

.markdown-body code {
  @apply font-mono text-sm;
}

.markdown-body p {
  @apply leading-relaxed mb-4 last:mb-0;
}

.markdown-body a {
  @apply text-purple-400 hover:text-purple-300 transition-colors;
}

.markdown-body ul,
.markdown-body ol {
  @apply my-4 pl-6;
}

.markdown-body li {
  @apply mb-2;
}
</style>
