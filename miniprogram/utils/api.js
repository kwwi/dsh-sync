function _app() { return getApp() }

function request(path, method, data) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: `${_app().globalData.apiBase}${path}`,
      method,
      data,
      header: {
        'Content-Type': 'application/json',
        'X-Session-Id': _app().globalData.sessionId,
      },
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) resolve(res.data)
        else {
          const detail = typeof res.data === 'object' && res.data !== null ? res.data : { detail: res.data }
          reject({ statusCode: res.statusCode, ...detail })
        }
      },
      fail: reject,
    })
  })
}

module.exports = { request }
