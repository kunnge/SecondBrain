import request from '@/utils/request'

export interface ObsidianSyncJob {
  id: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  scanned_count: number
  added_count: number
  updated_count: number
  skipped_count: number
  deleted_count: number
  failed_count: number
  current_file: string | null
  errors: Array<{ path: string | null; error: string }>
  created_at: string
  started_at: string | null
  completed_at: string | null
}

export function startObsidianSync() {
  return request.post<ObsidianSyncJob>('/obsidian/sync')
}

export function getObsidianSync(taskId: string) {
  return request.get<ObsidianSyncJob>(`/obsidian/sync/${encodeURIComponent(taskId)}`)
}
