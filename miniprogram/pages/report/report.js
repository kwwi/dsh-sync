const { request } = require('../../utils/api')
const { requestPayment } = require('../../utils/wechat')

Page({
  data: {
    report: null,
    full: null,
    candidates: [],
    birthLines: [],
    fateText: '',
    namingAdviceText: '',
    needPayment: false,
    showProfessional: false,
    reportId: '',
    errorMsg: '',
  },

  async onLoad(options) {
    const id = options.id
    this.setData({ reportId: id })
    try {
      const preview = await request(`/api/v1/report/${id}?tier=preview`, 'GET')
      let full = null
      let needPayment = false
      try {
        full = await request(`/api/v1/report/${id}?tier=full`, 'GET')
      } catch (e) {
        console.log('tier=full 请求结果:', JSON.stringify(e))
        if (e && e.statusCode === 402) {
          needPayment = true
        }
      }

      const birth = (full && full.birth_summary) || preview.birth_summary || {}
      const birthLines = this._buildBirthLines(birth, preview)

      this.setData({
        report: preview,
        full,
        candidates: full ? full.candidates : (preview.candidates_preview || []),
        birthLines,
        fateText: full ? (full.fate_analysis && full.fate_analysis.vernacular) : (preview.fate_vernacular_excerpt || ''),
        namingAdviceText: full ? full.naming_advice : (preview.naming_advice_excerpt || ''),
        needPayment,
      })
    } catch (e) {
      const msg = (e && e.statusCode === 404) ? '报告不存在' : '加载失败，请返回重试'
      this.setData({ errorMsg: msg })
      wx.showToast({ title: msg, icon: 'none', duration: 2500 })
    }
  },

  _buildBirthLines(birth, preview) {
    const lines = []
    const add = (label, value) => { if (value) lines.push({ label, value }) }
    add('性别', birth['性别'])
    add('出生地点', birth['出生地点'])
    add('出生公历（北京）', birth['出生公历_北京'])
    add('出生公历（真太阳）', birth['出生公历_真太阳'])
    add('出生农历', birth['出生农历'])
    add('生辰八字', birth['生辰八字'])
    add('生肖', birth['生肖'])
    // 预览模式兜底
    if (!lines.length && preview && preview.bazi_summary) {
      add('四柱', preview.bazi_summary['四柱'])
      add('农历', preview.bazi_summary['农历'])
    }
    return lines
  },

  toggleProfessional() {
    this.setData({ showProfessional: !this.data.showProfessional })
  },

  goBack() {
    wx.navigateBack()
  },

  handleDownload() {
    wx.showLoading({ title: '生成 PDF 中…' })
    const app = getApp()
    const url = `${app.globalData.apiBase}/api/v1/report/${this.data.reportId}/download?sid=${app.globalData.sessionId}`
    wx.downloadFile({
      url,
      success: (res) => {
        wx.hideLoading()
        if (res.statusCode === 200) {
          wx.openDocument({
            filePath: res.tempFilePath,
            fileType: 'pdf',
            showMenu: true,
            success: () => {
              wx.showToast({ title: 'PDF 已打开', icon: 'success', duration: 1500 })
            },
            fail: (err) => {
              console.error('openDocument fail:', err)
              wx.showToast({ title: '打开失败，请重试', icon: 'none' })
            },
          })
        } else {
          wx.showToast({ title: '生成失败，请重试', icon: 'none' })
        }
      },
      fail: (err) => {
        wx.hideLoading()
        console.error('downloadFile fail:', err)
        wx.showToast({ title: '下载失败，请检查网络', icon: 'none', duration: 2000 })
      },
    })
  },

  async handleUnlock() {
    console.log('handleUnlock 被调用')
    try {
      const plans = await request('/api/v1/pricing/plans?channel=miniprogram', 'GET')
      console.log('定价方案:', JSON.stringify(plans))
      const plan = plans && plans[0]
      if (!plan) {
        wx.showToast({ title: '暂无可用付费方案', icon: 'none', duration: 2000 })
        return
      }
      if (plan.is_free) {
        const order = await request('/api/v1/payment/checkout', 'POST', {
          report_id: this.data.reportId,
          plan_sku: plan.sku,
        })
        if (order && order.status === 'paid') {
          const full = await request(`/api/v1/report/${this.data.reportId}?tier=full`, 'GET')
          this._applyFullReport(full)
          wx.showToast({ title: '已解锁完整报告', icon: 'success' })
        }
      } else {
        console.log('准备弹出 wx.showModal')
        wx.showModal({
          title: '解锁完整报告',
          content: `${plan.name}\n价格：¥${(plan.price_cents / 100).toFixed(2)}\n${plan.description}`,
          confirmText: '微信支付',
          cancelText: '兑换码',
          success: (res) => {
            console.log('wx.showModal success:', JSON.stringify(res))
            if (res.confirm) {
              wx.showLoading({ title: '拉起支付…' })
              requestPayment(this.data.reportId, plan.sku).then((paymentResult) => {
                wx.hideLoading()
                if (paymentResult.paid) {
                  request(`/api/v1/report/${this.data.reportId}?tier=full`, 'GET').then((full) => {
                    this._applyFullReport(full)
                    wx.showToast({ title: '支付成功！', icon: 'success' })
                  }).catch(() => {
                    wx.showToast({ title: '获取报告失败', icon: 'none' })
                  })
                } else if (paymentResult.cancelled) {
                  wx.showToast({ title: '已取消支付', icon: 'none' })
                }
              }).catch((err) => {
                wx.hideLoading()
                const errMsg = (err && (err.message || err.errMsg)) || JSON.stringify(err) || '支付失败'
                console.error('handleUnlock requestPayment 失败:', errMsg)
                wx.showToast({ title: errMsg, icon: 'none', duration: 4000 })
              })
            } else if (res.cancel) {
              this.showRedeemDialog()
            }
          },
          fail: (err) => {
            console.error('wx.showModal fail:', JSON.stringify(err))
          },
        })
      }
    } catch (e) {
      console.error('handleUnlock 失败:', JSON.stringify(e))
      wx.showToast({ title: '操作失败，请重试', icon: 'none', duration: 2000 })
    }
  },

  _applyFullReport(full) {
    const birth = full.birth_summary || {}
    const birthLines = this._buildBirthLines(birth)
    this.setData({
      full,
      candidates: full.candidates || [],
      birthLines,
      fateText: (full.fate_analysis && full.fate_analysis.vernacular) || '',
      namingAdviceText: full.naming_advice || '',
      needPayment: false,
    })
  },

  showRedeemDialog() {
    wx.showModal({
      title: '兑换码',
      editable: true,
      placeholderText: '请输入兑换码',
      success: (res) => {
        if (res.confirm && res.content) {
          request('/api/v1/payment/redeem', 'POST', {
            report_id: this.data.reportId,
            code: res.content.trim(),
          }).then(() => {
            return request(`/api/v1/report/${this.data.reportId}?tier=full`, 'GET')
          }).then((full) => {
            this._applyFullReport(full)
            wx.showToast({ title: '兑换成功！', icon: 'success' })
          }).catch(() => {
            wx.showToast({ title: '兑换码无效或已用完', icon: 'none' })
          })
        }
      },
    })
  },
})
