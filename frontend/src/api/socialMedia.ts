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
    summary?: {
      sections?: {
        official_ir?: number
        community_heat?: number
        news_fallback?: number
        other?: number
      }
      details?: {
        investor_questions?: number
        company_answers?: number
        heat_snapshots?: number
        keyword_snapshots?: number
        news_proxy_messages?: number
      }
      platforms?: Record<string, number>
    }
  }
}

export interface SocialMediaQueryRequest {
  symbol?: string
  symbols?: string[]
  platform?: string
  message_type?: string
  start_time?: string
  end_time?: string
  sentiment?: string
  importance?: string
  verified_only?: boolean
  keywords?: string[]
  hashtags?: string[]
  limit?: number
  skip?: number
}

export interface SocialMediaMessageItem {
  symbol: string
  message_id: string
  platform: string
  message_type: string
  content: string
  publish_time: string
  sentiment?: string
  sentiment_score?: number
  data_source?: string
  author?: {
    name?: string
    verified?: boolean
  }
}

export interface SocialMediaQueryResponse {
  messages: SocialMediaMessageItem[]
  count: number
  params?: Record<string, any>
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
  },
  queryMessages(request: SocialMediaQueryRequest) {
    return ApiClient.post<SocialMediaQueryResponse>(
      '/api/social-media/query',
      request
    )
  }
}
