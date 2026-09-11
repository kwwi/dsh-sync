/** 微信能力封装：登录、支付、隐私、内容审核 */

// 不能在模块顶层 getApp()，require 时 App 尚未初始化
function _app() { return getApp() }

// ── 微信登录 ──

let _loginPromise = null

function login() {
  if (_loginPromise) return _loginPromise

  _loginPromise = new Promise((resolve, reject) => {
    wx.login({
      success(res) {
        if (!res.code) {
          _loginPromise = null
          reject(new Error('wx.login 未返回 code'))
          return
        }
        wx.request({
          url: `${_app().globalData.apiBase}/api/v1/auth/wechat-login`,
          method: 'POST',
          data: { code: res.code },
          success(r) {
            if (r.statusCode === 200 && r.data && r.data.session_id) {
              _app().globalData.sessionId = r.data.session_id
              _app().globalData.openid = r.data.openid
              wx.setStorageSync('session_id', r.data.session_id)
              wx.setStorageSync('openid', r.data.openid)
              resolve(r.data)
            } else {
              _loginPromise = null
              const detail = (r.data && r.data.detail) || `状态码 ${r.statusCode}`
              reject(new Error(`登录失败: ${detail}`))
            }
          },
          fail(err) {
            _loginPromise = null
            reject(err)
          },
        })
      },
      fail(err) {
        _loginPromise = null
        reject(err)
      },
    })
  })

  return _loginPromise
}

function getOpenid() {
  if (_app().globalData.openid) return _app().globalData.openid
  return wx.getStorageSync('openid') || ''
}

// ── 微信支付 ──

async function requestPayment(reportId, planSku) {
  let openid = getOpenid()

  // 如果未登录，先尝试重新登录
  if (!openid) {
    console.log('[requestPayment] openid 为空，尝试重新登录')
    try {
      const loginResult = await login()
      openid = loginResult.openid
      console.log('[requestPayment] 重新登录成功, openid:', openid)
    } catch (e) {
      const errMsg = (e && e.message) || JSON.stringify(e) || '未知错误'
      console.error('[requestPayment] 重新登录失败:', errMsg)

      // Dev 模式：登录失败时使用 mock openid，允许本地调试支付流程
      if (_app().globalData.apiBase.includes('127.0.0.1') || _app().globalData.apiBase.includes('localhost')) {
        openid = 'dev_openid_' + Date.now().toString(36)
        console.log('[requestPayment] DEV 模式：使用 mock openid:', openid)
        wx.setStorageSync('openid', openid)
        _app().globalData.openid = openid
      } else {
        throw new Error(`请先完成微信登录（${errMsg}）`)
      }
    }
  }

  return new Promise((resolve, reject) => {
    console.log('[requestPayment] 开始创建预支付订单, reportId:', reportId, 'planSku:', planSku)
    // 1. 后端创建预支付订单
    wx.request({
      url: `${_app().globalData.apiBase}/api/v1/payment/wechat-prepay`,
      method: 'POST',
      header: {
        'Content-Type': 'application/json',
        'X-Session-Id': _app().globalData.sessionId,
        'X-Openid': openid,
      },
      data: { report_id: reportId, plan_sku: planSku },
      success(res) {
        console.log('[requestPayment] 预支付响应:', res.statusCode, JSON.stringify(res.data))
        if (res.statusCode !== 200 || !res.data) {
          const errMsg = (res.data && res.data.detail) || '创建订单失败'
          console.error('[requestPayment] 创建预支付订单失败:', errMsg)
          reject(new Error(errMsg))
          return
        }
        const prepay = res.data
        console.log('[requestPayment] 准备拉起 wx.requestPayment')

        // 2. 唤起微信支付（dev 模式下直接模拟成功）
        if (_app().globalData.devMode || prepay._dev_mode) {
          console.log('[requestPayment] DEV 模式：模拟支付成功')
          resolve({ order_id: prepay.order_id, paid: true, _dev: true })
          return
        }

        wx.requestPayment({
          timeStamp: prepay.timeStamp,
          nonceStr: prepay.nonceStr,
          package: prepay.package,
          signType: prepay.signType || 'RSA',
          paySign: prepay.paySign,
          success() {
            console.log('[requestPayment] wx.requestPayment 成功')
            resolve({ order_id: prepay.order_id, paid: true })
          },
          fail(err) {
            console.error('[requestPayment] wx.requestPayment 失败:', JSON.stringify(err))
            if (err.errMsg && err.errMsg.includes('cancel')) {
              resolve({ order_id: prepay.order_id, paid: false, cancelled: true })
            } else {
              reject(err)
            }
          },
        })
      },
      fail(err) {
        console.error('[requestPayment] 网络请求失败:', JSON.stringify(err))
        reject(err)
      },
    })
  })
}

// ── 隐私弹窗 ──

let _privacyResolved = false
let _privacyResolveFn = null   // wx.onNeedPrivacyAuthorization 回调的 resolve 函数
let _onPrivacyNeeded = null    // 外部注册的回调，用于通知页面展示弹窗

/** 注册隐私授权监听（基础库 2.32.3+，需配合 __usePrivacyCheck__: true） */
function setupPrivacyListener() {
  if (typeof wx.onNeedPrivacyAuthorization === 'function') {
    wx.onNeedPrivacyAuthorization((resolve) => {
      _privacyResolveFn = resolve
      // 通知页面展示自定义隐私弹窗
      if (typeof _onPrivacyNeeded === 'function') {
        _onPrivacyNeeded()
      }
    })
  }
}

/** 页面注册「需要展示隐私弹窗」的回调 */
function onPrivacyNeeded(callback) {
  _onPrivacyNeeded = callback
}

function checkPrivacy() {
  return new Promise((resolve) => {
    if (_privacyResolved) {
      resolve({ needAuth: false })
      return
    }

    // 检查是否需要隐私授权（基础库 2.32.3+）
    if (typeof wx.getPrivacySetting === 'function') {
      wx.getPrivacySetting({
        success(res) {
          if (res.needAuthorization) {
            resolve({ needAuth: true })
          } else {
            _privacyResolved = true
            resolve({ needAuth: false })
          }
        },
        fail() {
          resolve({ needAuth: false })
        },
      })
    } else {
      _privacyResolved = true
      resolve({ needAuth: false })
    }
  })
}

function agreePrivacy() {
  _privacyResolved = true
  // 通知微信官方隐私流程：用户已同意
  if (_privacyResolveFn) {
    _privacyResolveFn({ event: 'agree', buttonId: 'agree-btn' })
    _privacyResolveFn = null
  }
  // 同时调用 requirePrivacyAuthorize 确保官方状态同步
  if (typeof wx.requirePrivacyAuthorize === 'function') {
    wx.requirePrivacyAuthorize({
      success() { /* 已授权 */ },
      fail() { /* 同步失败，不影响已有逻辑 */ },
    })
  }
}

function rejectPrivacy() {
  // 通知微信官方隐私流程：用户已拒绝
  if (_privacyResolveFn) {
    _privacyResolveFn({ event: 'disagree' })
    _privacyResolveFn = null
  }
}

function openPrivacyContract() {
  if (typeof wx.openPrivacyContract === 'function') {
    wx.openPrivacyContract({})
  }
}

// ── 内容安全审核 ──

function checkContent(content, scene = 1) {
  return new Promise((resolve, reject) => {
    const openid = getOpenid()
    wx.request({
      url: `${_app().globalData.apiBase}/api/v1/security/content-check`,
      method: 'POST',
      header: {
        'Content-Type': 'application/json',
        'X-Session-Id': _app().globalData.sessionId,
      },
      data: { content, scene, openid },
      success(res) {
        if (res.statusCode === 200 && res.data) {
          resolve(res.data)
        } else {
          // 接口不可用时放行
          resolve({ passed: true, label: 100 })
        }
      },
      fail() {
        // 网络异常时放行（避免阻塞用户体验）
        resolve({ passed: true, label: 100, suggestion: 'bypass' })
      },
    })
  })
}

module.exports = {
  login,
  getOpenid,
  requestPayment,
  setupPrivacyListener,
  onPrivacyNeeded,
  checkPrivacy,
  agreePrivacy,
  rejectPrivacy,
  openPrivacyContract,
  checkContent,
}
