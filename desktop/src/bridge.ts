import { invoke } from '@tauri-apps/api/core'
import { listen, type UnlistenFn } from '@tauri-apps/api/event'
declare global {
  interface Window {
    __TAURI_INTERNALS__?: unknown
    __TEST_BRIDGE__?: (command: string, args: unknown) => Promise<unknown>
  }
}
export async function call<T>(command: string, args: Record<string, unknown> = {}): Promise<T> {
  if (window.__TAURI_INTERNALS__) return invoke<T>(command, args)
  if (import.meta.env.DEV && window.__TEST_BRIDGE__)
    return window.__TEST_BRIDGE__(command, args) as Promise<T>
  throw { code: 'desktop_required', message: '请从桌面应用打开；浏览器预览未连接本地数据库。' }
}
export async function subscribe(event: string, handler: () => void): Promise<UnlistenFn> {
  return window.__TAURI_INTERNALS__ ? listen(event, handler) : () => {}
}
export function errorText(error: unknown): string {
  return error && typeof error === 'object' && 'message' in error
    ? String(error.message)
    : '操作失败，请重试；输入内容仍保留。'
}
