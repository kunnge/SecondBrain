/**
 * 后端统一返回格式
 */

export interface Result<T = any> {
  code: number
  message: string
  data: T
}

/**
 * 请求参数
 */
interface RequestOptions extends RequestInit {
  params?: Record<string, any>
}

class Request {
  /**
   * 通用请求
   */
  async request<T = any>(url: string, options: RequestOptions = {}): Promise<Result<T>> {
    const { params, headers, ...fetchOptions } = options
    url = `${import.meta.env.VITE_API_BASE_URL}${url}`
    // 处理 GET 参数
    if (params) {
      const searchParams = new URLSearchParams()

      Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null) {
          searchParams.append(key, String(value))
        }
      })

      url += `?${searchParams.toString()}`
    }

    const response = await fetch(url, {
      headers: {
        ...headers,
      },
      ...fetchOptions,
    })

    // HTTP 请求失败
    if (!response.ok) {
      throw new Error(`HTTP Error：${response.status}`)
    }

    // 返回统一格式
    return response.json()
  }

  /**
   * GET
   */
  get<T = any>(url: string, params?: Record<string, any>) {
    return this.request<T>(url, {
      method: 'GET',
      params,
    })
  }

  /**
   * POST
   */
  post<T = any>(url: string, data?: any) {
    return this.request<T>(url, {
      headers: {
        'Content-Type': 'application/json',
      },
      method: 'POST',
      body: JSON.stringify(data),
    })
  }

  /**
   * 文件上传
   */
  upload<T = any>(url: string, data: FormData) {
    return this.request<T>(url, {
      method: 'POST',
      body: data,
    })
  }

  /**
   * PUT
   */
  put<T = any>(url: string, data?: any) {
    return this.request<T>(url, {
      method: 'PUT',
      body: JSON.stringify(data),
    })
  }

  /**
   * DELETE
   */
  delete<T = any>(url: string, data?: any) {
    return this.request<T>(url, {
      method: 'DELETE',
      body: JSON.stringify(data),
    })
  }

  /**
   * AI 流式请求
   */
  async *stream(url: string, options: RequestOptions = {}): AsyncGenerator<string> {
    const response = await fetch(url, {
      headers: {
        ...options.headers,
      },
      ...options,
    })

    if (!response.ok) {
      throw new Error(`HTTP Error：${response.status}`)
    }

    const reader = response.body?.getReader()

    if (!reader) {
      throw new Error('响应流为空')
    }

    const decoder = new TextDecoder()

    while (true) {
      const { done, value } = await reader.read()

      if (done) break

      yield decoder.decode(value, {
        stream: true,
      })
    }
  }
}

export default new Request()
