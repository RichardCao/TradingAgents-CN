import { ApiClient } from './request'

export interface SocialMediaSyncNativeRequest {
  symbol: string
  days_back?: number
  max_items?: number
  allow_news_fallback?: boolean
}

export interface SocialMediaSyncFromNewsRequest {
  symbol: string
  hours_back?: number
  max_items?: number
}

export interface SocialMediaSyncResponse {
  symbol: string
  sync_stats: {
    source: string
    source_details?: string[]
    total_source_items?: number
    total_news?: number
    generated_messages: number
    saved_messages: number
    failed_messages: number
    latest_publish_time?: string | null
    fallback_used?: boolean
    fallback_source?: string | null
  }
}

export const socialMediaApi = {
  syncAShareNative(request: SocialMediaSyncNativeRequest) {
    return ApiClient.post<SocialMediaSyncResponse>(
      '/api/social-media/sync/a-share-native',
      request,
      {
        timeout: 120000
      }
    )
  },
  syncFromNews(request: SocialMediaSyncFromNewsRequest) {
    return ApiClient.post<SocialMediaSyncResponse>(
      '/api/social-media/sync/from-news',
      request,
      {
        timeout: 120000
      }
    )
  }
}
