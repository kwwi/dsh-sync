const { checkPrivacy, agreePrivacy, rejectPrivacy, openPrivacyContract, onPrivacyNeeded } = require('../../utils/wechat')
const { request } = require('../../utils/api')
const app = getApp()

Page({
  data: {
    showPrivacy: false,
    history: [],
  },

  onLoad() {
    // 注册隐私回调：当微信系统需要隐私授权时展示自定义弹窗
    onPrivacyNeeded(() => {
      this.setData({ showPrivacy: true })
    })
  },

  onShow() {
    // 检查是否需要隐私授权
    if (!app.globalData.privacyChecked) {
      this.setData({ showPrivacy: true })
    }
    // 加载历史报告
    this.loadHistory()
  },

  async loadHistory() {
    try {
      const history = await request('/api/v1/reports/history', 'GET')
      this.setData({ history: history || [] })
    } catch (_) {
      this.setData({ history: [] })
    }
  },

  goInput() {
    if (!app.globalData.privacyChecked) {
      this.setData({ showPrivacy: true })
      return
    }
    wx.navigateTo({ url: '/pages/input/input' })
  },

  goReport(e) {
    const id = e.currentTarget.dataset.id
    wx.navigateTo({ url: `/pages/report/report?id=${id}` })
  },

  handleAgreePrivacy() {
    agreePrivacy()
    app.globalData.privacyChecked = true
    this.setData({ showPrivacy: false })
    wx.navigateTo({ url: '/pages/input/input' })
  },

  handleRejectPrivacy() {
    rejectPrivacy()
    wx.showToast({ title: '需要同意隐私政策才能使用', icon: 'none', duration: 2000 })
  },

  handleOpenPrivacy() {
    openPrivacyContract()
  },
})
