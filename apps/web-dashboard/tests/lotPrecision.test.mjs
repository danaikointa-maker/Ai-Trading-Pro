import assert from 'node:assert/strict'
import test from 'node:test'

import { lotPrecision } from '../src/lib/lotPrecision.js'

test('lot display precision follows common broker volume steps', () => {
  assert.equal(lotPrecision(0.01), 2)
  assert.equal(lotPrecision(0.001), 3)
  assert.equal(lotPrecision(0.25), 2)
  assert.equal(lotPrecision(0.0001), 4)
})

test('invalid volume steps use a safe display fallback', () => {
  assert.equal(lotPrecision(0), 2)
  assert.equal(lotPrecision(Number.NaN), 2)
  assert.equal(lotPrecision(Number.POSITIVE_INFINITY), 2)
})
