# RestoKit palette A · Signal

Logo: concept 2, Meter Face (moisture-meter body with two probe pins, a screen face with droplet eyes, and an amber reading-level bar).
Wordmark: Exo 2 SemiBold, outlined to SVG paths (no font dependency).

| Role | Name | Hex | Use |
|---|---|---|---|
| Primary blue | Signal Blue | `#1D69C6` | Mark body, buttons, links, "Kit" on light |
| Accent orange | Amber | `#F08A24` | Reading bar, indicators, badges (ink text), "Kit" on dark |
| Dark neutral | Ink Navy | `#0C1B2E` | Body text on light, dark site background, screen face, probe pins |
| Light neutral | Poly White | `#EEF3F9` | Page background, text on dark, probe pins on dark |
| Support | Wave Cyan | `#3CC4F2` | Droplet eyes, data highlights and links on dark only |

## Contrast (WCAG 2.x)

| Pair | Ratio | Grade |
|---|---|---|
| Ink Navy text on Poly White | 15.5:1 | AAA |
| Signal Blue text on Poly White | 4.8:1 | AA |
| White text on Signal Blue | 5.4:1 | AA |
| Ink Navy text on Amber | 6.9:1 | AA |
| Wave Cyan on Ink Navy | 8.6:1 | AAA |
| Amber text on Ink Navy | 6.9:1 | AA |
| White text on Amber | 2.5:1 | fail: avoid for text (large/UI only with care) |
| Wave Cyan on Poly White | 1.8:1 | fail: never use cyan as text on light |

## Files

- `restokit_logo_horizontal_light.svg/.png`: lockup for light backgrounds ("Resto" Ink Navy, "Kit" Signal Blue)
- `restokit_logo_horizontal_dark.svg/.png`: lockup for dark backgrounds ("Resto" Poly White, "Kit" Amber, Poly White pins)
- `restokit_icon.svg`: icon, full detail; `restokit_icon_small.svg`: simplified cut for 32 px and below
- `restokit_icon_{512,180,64,32,16}.png`: 32 and 16 use the simplified cut
- `restokit_icon_on_dark.svg`, `restokit_icon_on_dark_small.svg`, `restokit_icon_on_dark_{512,32}.png`: Poly White probe pins so they stay visible on dark
