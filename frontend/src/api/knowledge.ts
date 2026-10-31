import request from '@/utils/request'

export interface KnowledgeDocument {
  id: string
  filename: string
  title: string
  summary: string
  category: string
  tags: string[]
  keywords: string[]
  content?: string
  size: number
  processing_status: 'pending' | 'processing' | 'completed' | 'failed'
  metadata_status: 'pending' | 'processing' | 'completed' | 'failed'
  metadata_error: string | null
  created_at: string
  updated_at: string
}

export interface DocumentListResponse {
  items: KnowledgeDocument[]
  total: number
  page: number
  page_size: number
  total_pages: number
  categories: string[]
  tags: string[]
}

export interface DocumentListQuery {
  q?: string
  category?: string
  tag?: string
  page: number
  page_size: number
}

export function listDocuments(query: DocumentListQuery) {
  return request.get<DocumentListResponse>('/documents', query)
}

export function getDocument(id: string) {
  return request.get<KnowledgeDocument>(`/documents/${encodeURIComponent(id)}`)
}

export function updateDocument(
  id: string,
  metadata: Pick<KnowledgeDocument, 'title' | 'summary' | 'category' | 'tags' | 'keywords'>,
) {
  return request.put<KnowledgeDocument>(`/documents/${encodeURIComponent(id)}`, metadata)
}

