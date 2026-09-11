const { request } = require('../../utils/api')
const { STEP_ORDER, STEP_LABELS, generateReportStream } = require('../../utils/reportGenerate')
const { checkContent } = require('../../utils/wechat')

const MUNICIPALITIES = new Set(['北京市', '天津市', '上海市', '重庆市'])

const NAMES_IDLE_TIPS = [
  '正在从《诗经》《楚辞》中抽取意象…',
  '正在斟酌平仄与五行喜用…',
  '正在组合姓与典籍用字…',
  '好名字值得多等片刻…',
]
const NAMES_TIP_INTERVAL_MS = 3500

function buildProgressSteps(currentStep, completed) {
  const curIdx = STEP_ORDER.indexOf(currentStep)
  return STEP_ORDER.map((id, i) => ({
    id,
    label: STEP_LABELS[id],
    state: completed.includes(id) || (curIdx >= 0 && i < curIdx) ? 'done' : id === currentStep ? 'active' : '',
  }))
}

Page({
  data: {
    surname: '',
    gender: 'male',
    genders: ['男', '女'],
    genderIndex: 0,
    date: '',
    time: '',
    loading: false,
    progressVisible: false,
    progressTitle: '',
    progressSummary: '',
    progressDisplay: '',
    progressIndex: 1,
    progressSteps: [],
    completedSteps: [],
    provinces: [],
    cities: [],
    districts: [],
    provinceIndex: -1,
    cityIndex: -1,
    districtIndex: -1,
    birthPlace: null,
    regionLabel: '请选择出生地',
  },
  async onLoad() {
    await this.loadProvinces()
  },
  onHide() {
    this._clearProgressTimers()
  },
  onUnload() {
    this._clearProgressTimers()
  },
  _clearProgressTimers() {
    if (this._typeTimer) {
      clearInterval(this._typeTimer)
      this._typeTimer = null
    }
    this._stopNamesTips()
  },
  _stopNamesTips() {
    if (this._namesTipTimer) {
      clearInterval(this._namesTipTimer)
      this._namesTipTimer = null
    }
  },
  _startNamesTips() {
    this._stopNamesTips()
    this._namesTipIdx = 0
    this._namesTipTimer = setInterval(() => {
      if (this._lastProgressStep !== 'names') {
        this._stopNamesTips()
        return
      }
      this._namesTipIdx = (this._namesTipIdx + 1) % NAMES_IDLE_TIPS.length
      this._startTypewriter(NAMES_IDLE_TIPS[this._namesTipIdx])
    }, NAMES_TIP_INTERVAL_MS)
  },
  _startTypewriter(text) {
    if (this._typeTimer) clearInterval(this._typeTimer)
    this._typeIndex = 0
    this.setData({ progressDisplay: '', progressSummary: text })
    if (!text) return
    this._typeTimer = setInterval(() => {
      this._typeIndex += 1
      if (this._typeIndex > text.length) {
        clearInterval(this._typeTimer)
        this._typeTimer = null
        return
      }
      this.setData({ progressDisplay: text.slice(0, this._typeIndex) })
    }, 28)
  },
  _onProgress(ev) {
    const completed = [...this.data.completedSteps]
    if (this._lastProgressStep && this._lastProgressStep !== ev.step && !completed.includes(this._lastProgressStep)) {
      completed.push(this._lastProgressStep)
    }
    this._lastProgressStep = ev.step
    const idx = STEP_ORDER.indexOf(ev.step) + 1
    this.setData({
      progressVisible: true,
      progressTitle: ev.title,
      progressIndex: idx > 0 ? idx : 1,
      completedSteps: completed,
      progressSteps: buildProgressSteps(ev.step, completed),
    })
    this._startTypewriter(ev.summary || '')
    // 典籍起名阶段：有真实 SSE 时重置轮播；离开该阶段则停止
    if (ev.step === 'names') {
      this._startNamesTips()
    } else {
      this._stopNamesTips()
    }
  },
  onSurname(e) { this.setData({ surname: e.detail.value }) },
  onDate(e) { this.setData({ date: e.detail.value }) },
  onTime(e) { this.setData({ time: e.detail.value }) },
  onGender(e) { this.setData({ genderIndex: Number(e.detail.value), gender: this.data.genders[Number(e.detail.value)] === '男' ? 'male' : 'female' }) },
  async loadProvinces() {
    try {
      const provinces = await request('/api/v1/regions', 'GET')
      console.log('[loadProvinces] 获取到', provinces.length, '个省份')
      this.setData({ provinces })
    } catch (e) {
      console.error('[loadProvinces] 加载省份失败:', JSON.stringify(e))
      // 网络不可达时使用内置备选列表
      this.setData({
        provinces: [
          { code: '110000', name: '北京市' },
          { code: '310000', name: '上海市' },
          { code: '440100', name: '广州市' },
        ],
      })
      wx.showToast({ title: '加载地区列表失败，已使用简要列表', icon: 'none', duration: 3000 })
    }
  },
  async loadChildren(parent) {
    return request(`/api/v1/regions?parent=${encodeURIComponent(parent)}`, 'GET')
  },
  async geocode(code) {
    return request(`/api/v1/regions/geocode?code=${encodeURIComponent(code)}`, 'GET')
  },
  formatLabel(place) {
    const parts = [place.province, place.city, place.district].filter(Boolean)
    return `${parts.join(' ')}（${place.longitude.toFixed(2)}°, ${place.latitude.toFixed(2)}°）`
  },
  async selectRegionByCode(code) {
    const place = await this.geocode(code)
    const provinceIndex = this.data.provinces.findIndex((p) => p.name === place.province)
    if (provinceIndex < 0) return
    const province = this.data.provinces[provinceIndex]
    if (MUNICIPALITIES.has(province.name)) {
      const districts = await this.loadChildren(province.code)
      const districtIndex = districts.findIndex((d) => d.code === code || d.name === place.district)
      this.setData({
        cities: [],
        districts,
        provinceIndex,
        cityIndex: -1,
        districtIndex: districtIndex >= 0 ? districtIndex : 0,
        birthPlace: place,
        regionLabel: this.formatLabel(place),
      })
      return
    }
    const cities = await this.loadChildren(province.code)
    const cityIndex = cities.findIndex((c) => c.name === place.city)
    let districts = []
    let districtIndex = -1
    if (cityIndex >= 0 && cities[cityIndex].has_children) {
      districts = await this.loadChildren(cities[cityIndex].code)
      districtIndex = districts.findIndex((d) => d.name === place.district)
    }
    this.setData({
      cities,
      districts,
      provinceIndex,
      cityIndex: cityIndex >= 0 ? cityIndex : 0,
      districtIndex: districtIndex >= 0 ? districtIndex : 0,
      birthPlace: place,
      regionLabel: this.formatLabel(place),
    })
  },
  async onProvince(e) {
    const provinceIndex = Number(e.detail.value)
    const province = this.data.provinces[provinceIndex]
    if (MUNICIPALITIES.has(province.name)) {
      const districts = await this.loadChildren(province.code)
      this.setData({
        provinceIndex,
        cities: [],
        districts,
        cityIndex: -1,
        districtIndex: -1,
        birthPlace: null,
        regionLabel: '请选择区',
      })
      return
    }
    const cities = await this.loadChildren(province.code)
    this.setData({
      provinceIndex,
      cities,
      districts: [],
      cityIndex: -1,
      districtIndex: -1,
      birthPlace: null,
      regionLabel: '请选择城市',
    })
    if (cities.length === 1 && !cities[0].has_children) {
      await this.applySelection(provinceIndex, 0, -1)
    }
  },
  async onCity(e) {
    const cityIndex = Number(e.detail.value)
    await this.applySelection(this.data.provinceIndex, cityIndex, -1)
  },
  async onDistrict(e) {
    const districtIndex = Number(e.detail.value)
    const province = this.data.provinces[this.data.provinceIndex]
    if (MUNICIPALITIES.has(province.name)) {
      const code = this.data.districts[districtIndex].code
      const place = await this.geocode(code)
      this.setData({
        districtIndex,
        birthPlace: place,
        regionLabel: this.formatLabel(place),
      })
      return
    }
    await this.applySelection(this.data.provinceIndex, this.data.cityIndex, districtIndex)
  },
  async applySelection(provinceIndex, cityIndex, districtIndex) {
    const city = this.data.cities[cityIndex]
    if (!city) return
    let code = city.code
    let districts = this.data.districts
    if (city.has_children) {
      if (districts.length === 0) {
        districts = await this.loadChildren(city.code)
      }
      if (districtIndex < 0) {
        this.setData({ cityIndex, districts, districtIndex: -1, birthPlace: null, regionLabel: '请选择区/县' })
        return
      }
      code = districts[districtIndex].code
    }
    const place = await this.geocode(code)
    this.setData({
      provinceIndex,
      cityIndex,
      districtIndex: city.has_children ? districtIndex : -1,
      districts,
      birthPlace: place,
      regionLabel: this.formatLabel(place),
    })
  },
  async submit() {
    if (this.data.loading) return

    if (!this.data.surname || !this.data.surname.trim()) {
      wx.showToast({ title: '请输入姓氏', icon: 'none' })
      return
    }
    if (!this.data.date) {
      wx.showToast({ title: '请选择出生日期', icon: 'none' })
      return
    }
    if (!this.data.time) {
      wx.showToast({ title: '请选择出生时间', icon: 'none' })
      return
    }
    if (!this.data.birthPlace) {
      wx.showToast({ title: '请选择出生地', icon: 'none' })
      return
    }

    // 内容安全审核：检查姓氏
    const surname = this.data.surname.trim()
    const checkResult = await checkContent(surname, 1)
    if (!checkResult.passed) {
      wx.showToast({ title: '输入内容含违规信息，请修改', icon: 'none', duration: 3000 })
      return
    }

    const [h, min] = this.data.time.split(':').map(Number)
    const bp = this.data.birthPlace
    this._lastProgressStep = ''
    this.setData({
      loading: true,
      progressVisible: true,
      completedSteps: [],
      progressSteps: buildProgressSteps('bazi', []),
      progressTitle: '八字排盘',
      progressIndex: 1,
    })
    this._startTypewriter('正在启动推算引擎…')
    try {
      const body = {
        surname: this.data.surname.trim(),
        gender: this.data.gender,
        birth_datetime: `${this.data.date}T${String(h).padStart(2, '0')}:${String(min).padStart(2, '0')}:00+08:00`,
        birth_place: {
          province: bp.province,
          city: bp.city,
          district: bp.district,
          longitude: bp.longitude,
          latitude: bp.latitude,
        },
        output_count: 10,
      }
      const res = await generateReportStream(body, (ev) => this._onProgress(ev))
      this._onProgress({ step: 'finalize', title: '汇总报告', summary: '报告已生成，正在跳转…' })
      wx.navigateTo({ url: `/pages/report/report?id=${res.report_id}` })
    } catch (e) {
      const msg = (e && e.message) ? e.message : '生成失败，请重试'
      wx.showToast({ title: msg, icon: 'none', duration: 3000 })
    } finally {
      this._clearProgressTimers()
      this.setData({ loading: false, progressVisible: false })
    }
  },
})
