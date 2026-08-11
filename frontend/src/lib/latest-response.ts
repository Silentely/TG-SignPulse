/**
 * 响应序号守卫：收敛「++seq 取号、比对 seq 丢弃过期响应」样板。
 *
 * 每处请求流（列表加载/详情/搜索防抖等）创建独立实例：
 * - next()：发起请求前取新序号；
 * - isCurrent(id)：响应返回时校验是否仍为最新，过期返回 false；
 * - invalidate()：使全部在途响应失效（关闭/重置场景）。
 *
 * 注意：本守卫只管理序号，不触碰 loading 状态；
 * 调用方仍需在 finally 中用 isCurrent(seq) 配对复位 loading。
 */
export function useLatestResponseGuard() {
  let seq = 0;
  return {
    /** 发起请求前取一个新序号 */
    next(): number {
      seq += 1;
      return seq;
    },
    /** 响应返回时校验：id 是否仍为最新序号 */
    isCurrent(id: number): boolean {
      return id === seq;
    },
    /** 使全部在途响应失效（等价于 seq 自增一次） */
    invalidate(): void {
      seq += 1;
    },
  };
}
