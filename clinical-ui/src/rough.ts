/** Small seeded random generator, so a sheet keeps the same torn edge on every render. */
function rng(seed: string) {
  let h = 2166136261
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return () => {
    h ^= h << 13
    h ^= h >>> 17
    h ^= h << 5
    return ((h >>> 0) % 10000) / 10000
  }
}

/**
 * A CSS clip-path polygon whose four edges wobble by a few pixels, like paper torn from a pad.
 * `amp` is the largest wobble in pixels.
 */
export function roughClip(seed: string, amp = 4): string {
  const r = rng(seed)
  const pts: string[] = []
  const jitter = (max: number) => (r() * max).toFixed(1)

  for (let x = 0; x <= 100; x += 2.5) pts.push(`${x}% ${jitter(amp)}px`)
  for (let y = 5; y <= 95; y += 6) pts.push(`calc(100% - ${jitter(amp * 0.7)}px) ${y}%`)
  for (let x = 100; x >= 0; x -= 2.5) pts.push(`${x}% calc(100% - ${jitter(amp)}px)`)
  for (let y = 95; y >= 5; y -= 6) pts.push(`${jitter(amp * 0.7)}px ${y}%`)

  return `polygon(${pts.join(', ')})`
}
