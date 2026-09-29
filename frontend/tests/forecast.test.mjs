import test from 'node:test'
import assert from 'node:assert/strict'
import { forecastTiming } from '../src/utils/forecastTiming.ts'
const job = (over) => ({ id: 'j', status: 'running', total: 1000, completed: 250, predicted: 240, skipped: 10, failed: 0,
  error: null, created_at: '2026-09-29T10:00:00Z', updated_at: '2026-09-29T10:05:00Z', ...over })
test('running forecast shows elapsed time, speed and remaining time', () => {
 assert.equal(forecastTiming(job({}), Date.parse('2026-09-29T10:05:00Z')), 'Прошло 5 мин 0 с · 50 датчиков/мин · осталось ≈ 15 мин 0 с')
})
test('finished forecast shows total duration without remaining time', () => {
 assert.equal(forecastTiming(job({ status: 'completed', completed: 1000, updated_at: '2026-09-29T11:10:00Z' })),
  'Заняло 1 ч 10 мин · 14 датчиков/мин')
})
test('job without timestamps shows nothing', () => {
 assert.equal(forecastTiming(job({ created_at: undefined })), '')
})
