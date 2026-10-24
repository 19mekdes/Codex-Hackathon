const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')
const REQUEST_TIMEOUT_MS = 30_000

async function request(path, options = {}) {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  let response, payload
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { ...options, signal: controller.signal })
    payload = await response.json()
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('The request timed out. Please try again.')
    if (response) throw new Error(`The API returned an unreadable response (HTTP ${response.status}).`)
    throw new Error('Could not reach the FixProof API. Check that the backend is running.')
  } finally {
    window.clearTimeout(timeout)
  }
  if (!response.ok) {
    throw new Error(payload?.error || payload?.detail || `Request failed (HTTP ${response.status}).`)
  }
  return payload
}

const postJson = (body) => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export function getHealth() {
  return request('/api/health/')
}

export async function analyzeCode({ language, code, error_message }) {
  if (language !== 'python') throw new Error('Only Python is supported right now.')
  const diagnosis = await request('/api/analyze/', postJson({ language, code, error_message }))
  if (
    !diagnosis || diagnosis.success !== true || typeof diagnosis.root_cause !== 'string' ||
    typeof diagnosis.explanation !== 'string' || typeof diagnosis.fixed_code !== 'string' ||
    !Array.isArray(diagnosis.changes) || diagnosis.changes.some((item) => typeof item !== 'string') ||
    !Array.isArray(diagnosis.suggested_tests) || diagnosis.suggested_tests.some((item) => (
      !item || typeof item.name !== 'string' || typeof item.description !== 'string'
    )) || !diagnosis.verification || typeof diagnosis.verification.status !== 'string'
  ) {
    throw new Error('The API returned an unexpected diagnosis. Please retry.')
  }
  return diagnosis
}

export function getFixtures() {
  return request('/api/fixtures/')
}

export function fixFixture(fixture_id) {
  return request('/api/fix/', postJson({ fixture_id }))
}

export function getRecorded() {
  return request('/api/recorded/')
}
