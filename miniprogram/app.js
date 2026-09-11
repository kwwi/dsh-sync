const { login, checkPrivacy, setupPrivacyListener } = require('./utils/wechat')

App({
  globalData: {
    apiBase: 'http://127.0.0.1:8000',
    sessionId: '',
    openid: '',
    privacyChecked: false,
    devMode: true,  // 本地开发模式，跳过真实微信支付
  },

  async onLaunch() {
    // 注册微信隐私授权监听（必须在 onLaunch 中尽早调用）
    setupPrivacyListener()

    // 根据小程序环境自动切换 API 地址
    try {
      const accountInfo = wx.getAccountInfoSync()
      const env = accountInfo.miniProgram.envVersion
      if (env === 'release') {
        this.globalData.apiBase = 'https://api.your-domain.com'
        this.globalData.devMode = false
      } else if (env === 'trial') {
        this.globalData.apiBase = 'https://staging.your-domain.com'
        this.globalData.devMode = false
      }
    } catch (_) { /* 保持 localhost 默认值 */ }

    // 恢复本地 session
    let sid = wx.getStorageSync('session_id')
    let openid = wx.getStorageSync('openid')
    if (sid) this.globalData.sessionId = sid
    if (openid) this.globalData.openid = openid

    // 隐私检查
    const privacy = await checkPrivacy()
    this.globalData.privacyChecked = !privacy.needAuth

    // 静默登录
    try {
      await login()
    } catch (_) {
      // 登录失败不阻塞，使用本地 session
      if (!sid) {
        sid = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}${Math.random().toString(36).slice(2)}`
        wx.setStorageSync('session_id', sid)
        this.globalData.sessionId = sid
      }
    }
  },
})
