import { useEffect, useRef, useState } from 'react'

/** 逐字打印动画 */
export function useTypewriter(text: string, speedMs = 28) {
  const [display, setDisplay] = useState('')
  const indexRef = useRef(0)

  useEffect(() => {
    setDisplay('')
    indexRef.current = 0
    if (!text) return

    const timer = window.setInterval(() => {
      indexRef.current += 1
      setDisplay(text.slice(0, indexRef.current))
      if (indexRef.current >= text.length) {
        window.clearInterval(timer)
      }
    }, speedMs)

    return () => window.clearInterval(timer)
  }, [text, speedMs])

  return display
}
