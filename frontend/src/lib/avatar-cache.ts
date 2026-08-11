/**
 * 账号头像 ObjectURL 缓存：每个账号在同一会话内仅保留一个活动 blob 引用，
 * 替换或整体释放时回收旧 URL，避免账号列表反复刷新时泄漏 blob 内存。
 */
export class AvatarUrlCache {
  private urls = new Map<string, string>()

  /** 返回已缓存的 ObjectURL；未加载过则返回 undefined */
  get(name: string): string | undefined {
    return this.urls.get(name)
  }

  /** 登记新 URL；若该账号已有旧 URL 且不同，先回收旧引用 */
  set(name: string, url: string): void {
    const prev = this.urls.get(name)
    if (prev && prev !== url) {
      revoke(prev)
    }
    this.urls.set(name, url)
  }

  /** 组件卸载时统一回收全部 ObjectURL */
  release(): void {
    for (const url of this.urls.values()) {
      revoke(url)
    }
    this.urls.clear()
  }
}

function revoke(url: string): void {
  try {
    URL.revokeObjectURL(url)
  } catch {
    /* ignore */
  }
}
