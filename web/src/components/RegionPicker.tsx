import { useEffect, useState } from 'react'
import { api } from '../services/api'

export type RegionItem = {
  code: string
  name: string
  longitude?: number | null
  latitude?: number | null
  has_children: boolean
}

export type BirthPlaceSelection = {
  province: string
  city: string
  district: string
  longitude: number
  latitude: number
  code: string
}

const MUNICIPALITIES = new Set(['北京市', '天津市', '上海市', '重庆市'])

type Props = {
  value?: string
  onChange: (place: BirthPlaceSelection) => void
}

export default function RegionPicker({ value, onChange }: Props) {
  const [provinces, setProvinces] = useState<RegionItem[]>([])
  const [cities, setCities] = useState<RegionItem[]>([])
  const [districts, setDistricts] = useState<RegionItem[]>([])
  const [provinceCode, setProvinceCode] = useState('')
  const [cityCode, setCityCode] = useState('')
  const [districtCode, setDistrictCode] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    api<RegionItem[]>('/api/v1/regions').then(setProvinces).catch(() => setProvinces([]))
  }, [])

  useEffect(() => {
    if (!value || provinces.length === 0) return
    if (value === districtCode || value === cityCode || value === provinceCode) return
    void hydrateFromCode(value)
  }, [value, provinces])

  async function loadChildren(parent: string) {
    return api<RegionItem[]>(`/api/v1/regions?parent=${encodeURIComponent(parent)}`)
  }

  async function hydrateFromCode(code: string) {
    setLoading(true)
    try {
      const place = await api<BirthPlaceSelection & { province: string; city: string; district: string }>(
        `/api/v1/regions/geocode?code=${encodeURIComponent(code)}`,
      )
      const prov = provinces.find((p) => p.name === place.province)
      if (!prov) return
      setProvinceCode(prov.code)
      if (MUNICIPALITIES.has(prov.name)) {
        const distRows = await loadChildren(prov.code)
        setCities([])
        setDistricts(distRows)
        const dist = distRows.find((d) => d.name === place.district) ?? distRows.find((d) => d.code === code)
        if (dist) {
          setDistrictCode(dist.code)
          onChange({ ...place, code: dist.code })
        }
        return
      }
      const cityRows = await loadChildren(prov.code)
      setCities(cityRows)
      const city = cityRows.find((c) => c.name === place.city)
      if (!city) {
        setCityCode('')
        setDistricts([])
        setDistrictCode(code)
        onChange({ ...place, code })
        return
      }
      setCityCode(city.code)
      if (!city.has_children) {
        setDistricts([])
        setDistrictCode(city.code)
        onChange({ ...place, code: city.code })
        return
      }
      const distRows = await loadChildren(city.code)
      setDistricts(distRows)
      const dist = distRows.find((d) => d.name === place.district) ?? distRows.find((d) => d.code === code)
      if (dist) {
        setDistrictCode(dist.code)
        onChange({ ...place, code: dist.code })
      }
    } finally {
      setLoading(false)
    }
  }

  async function emitGeocode(code: string) {
    const place = await api<BirthPlaceSelection & { province: string; city: string; district: string }>(
      `/api/v1/regions/geocode?code=${encodeURIComponent(code)}`,
    )
    onChange({ ...place, code })
  }

  async function onProvinceChange(code: string) {
    setProvinceCode(code)
    setCityCode('')
    setDistrictCode('')
    setDistricts([])
    setCities([])
    if (!code) return

    const prov = provinces.find((p) => p.code === code)
    const rows = await loadChildren(code)
    if (prov && MUNICIPALITIES.has(prov.name)) {
      setDistricts(rows)
      return
    }
    setCities(rows)
    const only = rows.length === 1 && !rows[0].has_children ? rows[0] : null
    if (only) {
      setCityCode(only.code)
      await emitGeocode(only.code)
    }
  }

  async function onCityChange(code: string) {
    setCityCode(code)
    setDistrictCode('')
    if (!code) {
      setDistricts([])
      return
    }
    const city = cities.find((c) => c.code === code)
    if (!city?.has_children) {
      setDistricts([])
      await emitGeocode(code)
      return
    }
    const rows = await loadChildren(code)
    setDistricts(rows)
    if (rows.length === 1) {
      setDistrictCode(rows[0].code)
      await emitGeocode(rows[0].code)
    }
  }

  async function onDistrictChange(code: string) {
    setDistrictCode(code)
    if (code) await emitGeocode(code)
  }

  const showCity = cities.length > 0
  const showDistrict = districts.length > 0
  const districtLabel = provinceCode && MUNICIPALITIES.has(provinces.find((p) => p.code === provinceCode)?.name ?? '')
    ? '区'
    : '区/县'

  return (
    <div className="region-picker">
      <label>
        省份
        <select
          value={provinceCode}
          disabled={loading}
          onChange={(e) => void onProvinceChange(e.target.value)}
          required
        >
          <option value="">请选择省份</option>
          {provinces.map((p) => (
            <option key={p.code} value={p.code}>{p.name}</option>
          ))}
        </select>
      </label>
      {showCity && (
        <label>
          城市
          <select
            value={cityCode}
            disabled={loading || !provinceCode}
            onChange={(e) => void onCityChange(e.target.value)}
            required
          >
            <option value="">请选择城市</option>
            {cities.map((c) => (
              <option key={c.code} value={c.code}>{c.name}</option>
            ))}
          </select>
        </label>
      )}
      {showDistrict && (
        <label>
          {districtLabel}
          <select
            value={districtCode}
            disabled={loading || (showCity && !cityCode)}
            onChange={(e) => void onDistrictChange(e.target.value)}
            required
          >
            <option value="">请选择{districtLabel}</option>
            {districts.map((d) => (
              <option key={d.code} value={d.code}>{d.name}</option>
            ))}
          </select>
        </label>
      )}
    </div>
  )
}
