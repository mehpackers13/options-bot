# Shares Lab — 2026-11-11T19:44:21Z

Can the volume-spike signal be traded with SHARES instead of options?

75 tickers, 3045 trading days (2014-10-02 to 2026-11-10), 18 variants (spike multiple x hold x momentum/reversal).
Entry is the NEXT day's open after the signal, exit the close [1, 3, 5] days later, 10bps round-trip costs charged on every trade.
Returns are averaged per DATE before any statistic: a volume spike is usually a market-wide event, so 40 tickers spiking together is one observation, not 40.
Discovery used dates before 2023-03-22; later dates were held out.

**Variants passing every gate: 0.** A variant must clear:

1. **sample** — >=30 independent dates;
2. **positive** — mean above 0 with the 95% CI above 0, after costs;
3. **beats baseline** — >= +10bps vs the same trade on non-signal days;
4. **out of sample** — >=10 held-out dates, still positive there;
5. **multiple comparisons** — Benjamini-Hochberg at q=0.10 across all 18 variants (cutoff p<=0.01137).

| Spike | Hold | Direction | Dates | Net (bps) | 95% range | Baseline | Edge | Holdout | p | Pass |
|---|---|---|---|---|---|---|---|---|---|---|
| 5x | 5d | momentum | 182 | +134.1 | [+34, +234] | -17.1 | +151.2 | -1.0 (81) | 0.0071 |  |
| 5x | 3d | momentum | 182 | +95.7 | [+20, +171] | -14.9 | +110.6 | -95.0 (81) | 0.011 |  |
| 5x | 1d | momentum | 182 | +39.0 | [-7, +85] | -14.2 | +53.3 | +0.7 (82) | 0.093 |  |
| 2x | 5d | momentum | 1547 | -3.4 | [-25, +18] | -17.2 | +13.8 | -43.0 (664) | 0.75 |  |
| 3x | 5d | momentum | 757 | -3.6 | [-45, +38] | -17.1 | +13.5 | -85.1 (301) | 0.86 |  |
| 3x | 3d | momentum | 757 | -3.8 | [-38, +30] | -14.9 | +11.1 | -125.5 (302) | 0.82 |  |
| 2x | 3d | momentum | 1547 | -4.5 | [-22, +13] | -15.1 | +10.5 | -51.1 (666) | 0.6 |  |
| 3x | 1d | momentum | 757 | -5.3 | [-24, +13] | -14.3 | +9.0 | -35.2 (303) | 0.57 |  |
| 2x | 1d | momentum | 1547 | -10.2 | [-20, -1] | -14.2 | +4.1 | -29.4 (668) | 0.034 |  |
| 2x | 1d | reversal | 1547 | -9.8 | [-19, -0] | -5.8 | -4.1 | +9.4 (668) | 0.042 |  |
| 3x | 1d | reversal | 757 | -14.7 | [-33, +4] | -5.7 | -9.0 | +15.2 (303) | 0.12 |  |
| 2x | 3d | reversal | 1547 | -15.5 | [-33, +2] | -4.9 | -10.5 | +31.1 (666) | 0.077 |  |
| 3x | 3d | reversal | 757 | -16.2 | [-50, +18] | -5.1 | -11.1 | +105.5 (302) | 0.34 |  |
| 3x | 5d | reversal | 757 | -16.4 | [-58, +25] | -2.9 | -13.5 | +65.1 (301) | 0.43 |  |
| 2x | 5d | reversal | 1547 | -16.6 | [-38, +5] | -2.8 | -13.8 | +23.0 (664) | 0.13 |  |
| 5x | 1d | reversal | 182 | -59.0 | [-105, -13] | -5.8 | -53.3 | -20.7 (82) | 0.011 |  |
| 5x | 3d | reversal | 182 | -115.7 | [-191, -40] | -5.1 | -110.6 | +75.0 (81) | 0.0022 |  |
| 5x | 5d | reversal | 182 | -154.1 | [-254, -54] | -2.9 | -151.2 | -19.0 (81) | 0.002 |  |

Paper research only. Nothing here places a trade, and a pass is a candidate for forward testing, not a proven edge.
