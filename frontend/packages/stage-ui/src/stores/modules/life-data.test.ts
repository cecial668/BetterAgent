import type { TothestarsConfig } from '../../services/betteragent-admin-api'

import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useLifeDataStore } from './life-data'

const SAMPLE_CONFIG: TothestarsConfig = {
  enabled: true,
  endpoint: 'http://127.0.0.1:8765',
  timeout_seconds: 2,
  permissions: {
    commissions: 'read_write_proactive',
    schedule: 'read_write_proactive',
    legends: 'read_only',
    wallet: 'read_only',
    journal: 'on_request',
    journal_text: 'hidden',
    focus: 'read_write_proactive',
  },
  write_mode: 'local',
  local_project_root: 'C:\\Path\\To\\ToTheStarsWeb',
  proactive: {
    enabled: false,
    quiet_hours: ['23:00', '07:00'],
    max_per_hour: 2,
    max_per_day: 6,
  },
}

function mockFetch(handler: (url: string, init?: RequestInit) => { ok: boolean, json?: unknown }) {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
    const result = handler(url, init)
    return {
      ok: result.ok,
      json: async () => result.json,
    } as Response
  }) as unknown as typeof fetch
}

describe('useLifeDataStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('loads config from admin and marks itself configured when enabled', async () => {
    mockFetch(() => ({ ok: true, json: { tothestars: SAMPLE_CONFIG } }))
    const store = useLifeDataStore()

    const cfg = await store.load()

    expect(cfg?.permissions.journal_text).toBe('hidden')
    expect(store.configured).toBe(true)
    expect(store.unreachable).toBe(false)
  })

  it('keeps config null and reports unreachable when admin is down', async () => {
    globalThis.fetch = vi.fn(async () => {
      throw new Error('ECONNREFUSED')
    }) as unknown as typeof fetch
    const store = useLifeDataStore()

    const cfg = await store.load()

    expect(cfg).toBeNull()
    expect(store.loaded).toBe(true)
    expect(store.unreachable).toBe(true)
    expect(store.configured).toBe(false)
  })

  it('patches permissions and adopts the server-read config after save', async () => {
    const calls: { url: string, method: string, body?: string }[] = []
    mockFetch((url, init) => {
      calls.push({ url, method: init?.method ?? 'GET', body: init?.body as string | undefined })
      if (init?.method === 'PATCH')
        return { ok: true, json: { status: 'ok', reloaded: true } }
      return {
        ok: true,
        json: { tothestars: { ...SAMPLE_CONFIG, permissions: { ...SAMPLE_CONFIG.permissions, commissions: 'hidden' } } },
      }
    })
    const store = useLifeDataStore()
    await store.load()

    const next = await store.save({ permissions: { commissions: 'hidden' } })

    expect(calls.map(call => call.method)).toEqual(['GET', 'PATCH', 'GET'])
    expect(JSON.parse(calls[1].body ?? '{}')).toEqual({ tothestars: { permissions: { commissions: 'hidden' } } })
    expect(next?.permissions.commissions).toBe('hidden')
    expect(store.config?.permissions.commissions).toBe('hidden')
  })

  it('keeps the previous config when the save fails', async () => {
    mockFetch((_url, init) => (init?.method === 'PATCH'
      ? { ok: false }
      : { ok: true, json: { tothestars: SAMPLE_CONFIG } }))
    const store = useLifeDataStore()
    await store.load()

    const next = await store.save({ enabled: false })

    expect(next).toBeNull()
    expect(store.config?.enabled).toBe(true)
  })
})
