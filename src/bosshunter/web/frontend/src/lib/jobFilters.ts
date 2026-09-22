import { useEffect, useState } from 'react'
import type { Job } from '@/hooks/useDashboard'

export interface JobFilters {
  query: string
  minScore: string
  salaryMin: string
  salaryMax: string
  status: string
  createdWithin: string
  sourcePlatform: string
  education: string
  recruitmentType: string
}

export const EMPTY_JOB_FILTERS: JobFilters = {
  query: '',
  minScore: '',
  salaryMin: '',
  salaryMax: '',
  status: '',
  createdWithin: '',
  sourcePlatform: '',
  education: '',
  recruitmentType: '',
}

export function useDebouncedValue<T>(value: T, delay: number) {
  const [debouncedValue, setDebouncedValue] = useState(value)

  useEffect(() => {
    const timeout = window.setTimeout(() => setDebouncedValue(value), delay)
    return () => window.clearTimeout(timeout)
  }, [value, delay])

  return debouncedValue
}

export function hasInvalidSalaryRange(filters: JobFilters) {
  if (filters.salaryMin === '' || filters.salaryMax === '') return false
  return Number(filters.salaryMin) > Number(filters.salaryMax)
}

export function hasActiveJobFilters(filters: JobFilters) {
  return Object.values(filters).some(value => value !== '')
}

function parseMonthlySalaryK(salary: string): [number, number] | null {
  const normalized = (salary || '').replace(/，/g, ',')
  if (!normalized || normalized.includes('面议') || /\/(?:天|日|小时|时)/.test(normalized)) return null
  const convert = (value: number, unit: string, source: string) => {
    if (unit.toLowerCase() === 'k') return value
    if (unit === '万') return value * 10
    if (unit === '千') return value
    return /(?:元\/月|元／月|块\/月|月薪|每月|月工资)/.test(source) ? value / 1000 : null
  }
  const range = normalized.match(/(\d+(?:\.\d+)?)\s*([kK万千]?)\s*[-~至到]\s*(\d+(?:\.\d+)?)\s*([kK万千]?)/)
  if (range) {
    const left = convert(Number(range[1]), range[2] || range[4], normalized)
    const right = convert(Number(range[3]), range[4] || range[2], normalized)
    if (left !== null && right !== null) return [Math.min(left, right), Math.max(left, right)]
  }
  const single = normalized.match(/(\d+(?:\.\d+)?)\s*([kK万千])/)
  if (single) {
    const value = convert(Number(single[1]), single[2], normalized)
    if (value !== null) return [value, /(?:以上|起|底薪)/.test(normalized) ? Number.POSITIVE_INFINITY : value]
  }
  const plainRange = normalized.match(/(\d+(?:\.\d+)?)\s*[-~至到]\s*(\d+(?:\.\d+)?)\s*(?:元|块)?\s*\/?\s*月/)
  if (plainRange) return [Math.min(Number(plainRange[1]), Number(plainRange[2])) / 1000, Math.max(Number(plainRange[1]), Number(plainRange[2])) / 1000]
  const plainSingle = normalized.match(/(\d+(?:\.\d+)?)\s*(?:元|块)\s*\/?\s*月/)
  if (plainSingle) return [Number(plainSingle[1]) / 1000, Number(plainSingle[1]) / 1000]
  return null
}

function parseCreatedAt(createdAt: string) {
  const value = (createdAt || '').trim()
  if (!value) return null
  const normalized = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(value)
    ? `${value.replace(' ', 'T')}Z`
    : value
  const date = new Date(normalized)
  return Number.isNaN(date.getTime()) ? null : date
}

function matchesCreatedWithin(createdAt: string, createdWithin: string) {
  if (!createdWithin) return true
  const created = parseCreatedAt(createdAt)
  if (!created) return false
  const now = new Date()
  if (createdWithin === 'today') {
    return created.getFullYear() === now.getFullYear()
      && created.getMonth() === now.getMonth()
      && created.getDate() === now.getDate()
  }
  const days = createdWithin === '3d' ? 3 : 7
  return now.getTime() - created.getTime() <= days * 24 * 60 * 60 * 1000
}

export function filterJobs(jobs: Job[], filters: JobFilters) {
  if (hasInvalidSalaryRange(filters)) return []
  const keyword = filters.query.trim().toLocaleLowerCase()
  const minimumScore = filters.minScore === '' ? null : Number(filters.minScore)
  const salaryMin = filters.salaryMin === '' ? null : Number(filters.salaryMin)
  const salaryMax = filters.salaryMax === '' ? null : Number(filters.salaryMax)
  const salaryEnabled = salaryMin !== null || salaryMax !== null

  return jobs.filter(job => {
    if (!matchesCreatedWithin(job.created_at, filters.createdWithin)) return false
    if (keyword) {
      const searchable = [job.title, job.company, job.jd, job.score_reason]
        .join('\n')
        .toLocaleLowerCase()
      if (!searchable.includes(keyword)) return false
    }
    if (minimumScore !== null && Number(job.score || 0) < minimumScore) return false
    if (filters.status && job.status !== filters.status) return false
    if (filters.sourcePlatform && job.source_platform !== filters.sourcePlatform) return false
    if (filters.recruitmentType && (job.recruitment_type || 'unknown') !== filters.recruitmentType) return false
    if (filters.education === 'unknown' && job.education) return false
    if (filters.education && filters.education !== 'unknown' && !(job.education || '').includes(filters.education)) return false
    if (salaryEnabled) {
      const salaryRange = parseMonthlySalaryK(job.salary || '')
      if (!salaryRange) return false
      const [jobMin, jobMax] = salaryRange
      if (salaryMin !== null && jobMax < salaryMin) return false
      if (salaryMax !== null && jobMin > salaryMax) return false
    }
    return true
  })
}
