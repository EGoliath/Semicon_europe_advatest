# Ternary benchmark – breakdown by file group

Source: results/bench_20261111_024447_ternary_full.csv (all 319 runs bit-exact).
Sizes include all headers, metadata, padding and checksums (whole .pzst file).

## A: 7 files, file alphabet 0/1/X (002 004 005 006 013 017 023)

| config | modes used | size (B) | ratio | vs .pat zip | vs plain zstd L9 | comp MB/s | decomp MB/s |
|---|---|---|---|---|---|---|---|
| raw:9 | raw×7 | 385,053,709 | 10.8x | 1.13x | +0% smaller | 188 | 756 |
| auto:none | bitpack×7 | 514,055,061 | 8.1x | 0.84x | -25% LARGER | 2342 | 982 |
| auto:9 | bitpack×7 | 179,222,394 | 23.3x | 2.42x | +115% smaller | 886 | 924 |
| t5:none | t5×7 | 975,781,891 | 4.3x | 0.45x | -61% LARGER | 589 | 1033 |
| t5:9 | t5×7 | 265,060,419 | 15.7x | 1.64x | +45% smaller | 326 | 832 |
| t5row:none | t5row×7 | 865,659,876 | 4.8x | 0.50x | -56% LARGER | 2097 | 1077 |
| t5row:9 | t5row×7 | 259,915,807 | 16.0x | 1.67x | +48% smaller | 429 | 868 |
| t5col:none | t5col×7 | 822,488,127 | 5.1x | 0.53x | -53% LARGER | 1997 | 1020 |
| t5col:9 | t5col×7 | 194,623,803 | 21.4x | 2.23x | +98% smaller | 642 | 889 |
| mixed:none | mixed×7 | 320,980,811 | 13.0x | 1.35x | +20% smaller | 2677 | 1031 |
| mixed:9 | mixed×7 | 179,248,061 | 23.3x | 2.42x | +115% smaller | 1015 | 952 |

## B: 2 files with true 3-symbol pins H/L/X (001 015)

| config | modes used | size (B) | ratio | vs .pat zip | vs plain zstd L9 | comp MB/s | decomp MB/s |
|---|---|---|---|---|---|---|---|
| raw:9 | raw×2 | 3,860 | 9.6x | 1.04x | +0% smaller | 2 | n/a (<10 ms) |
| auto:none | transpose×2 | 37,022 | 1.0x | 0.11x | -90% LARGER | 0 | 2 |
| auto:9 | transpose×2 | 3,334 | 11.1x | 1.21x | +16% smaller | 1 | n/a (<10 ms) |
| t5:none | t5×2 | 25,761 | 1.4x | 0.16x | -85% LARGER | 2 | n/a (<10 ms) |
| t5:9 | t5×2 | 4,523 | 8.2x | 0.89x | -15% LARGER | 1 | n/a (<10 ms) |
| t5row:none | t5×2 | 25,751 | 1.4x | 0.16x | -85% LARGER | 1 | n/a (<10 ms) |
| t5row:9 | t5×2 | 4,511 | 8.2x | 0.89x | -14% LARGER | 1 | n/a (<10 ms) |
| t5col:none | t5col×2 | 11,742 | 3.1x | 0.34x | -67% LARGER | 1 | n/a (<10 ms) |
| t5col:9 | t5col×2 | 3,185 | 11.6x | 1.26x | +21% smaller | 1 | n/a (<10 ms) |
| mixed:none | mixed×2 | 10,462 | 3.5x | 0.38x | -63% LARGER | 2 | 3 |
| mixed:9 | mixed×2 | 3,129 | 11.8x | 1.28x | +23% smaller | 1 | n/a (<10 ms) |

## C: 20 binary-only files (0/1)

| config | modes used | size (B) | ratio | vs .pat zip | vs plain zstd L9 | comp MB/s | decomp MB/s |
|---|---|---|---|---|---|---|---|
| raw:9 | raw×20 | 1,254,973,959 | 16.2x | 1.09x | +0% smaller | 266 | 870 |
| auto:none | bitpack×20 | 2,510,014,481 | 8.1x | 0.54x | -50% LARGER | 1849 | 1000 |
| auto:9 | bitpack×20 | 609,227,945 | 33.3x | 2.24x | +106% smaller | 865 | 972 |
| t5:none | t5×20 | 4,539,714,878 | 4.5x | 0.30x | -72% LARGER | 580 | 1028 |
| t5:9 | t5×20 | 1,042,055,425 | 19.5x | 1.31x | +20% smaller | 360 | 849 |
| t5row:none | t5row×20 | 4,154,527,393 | 4.9x | 0.33x | -70% LARGER | 1951 | 1099 |
| t5row:9 | t5row×20 | 1,010,574,905 | 20.1x | 1.35x | +24% smaller | 477 | 919 |
| t5col:none | t5col×20 | 4,016,022,617 | 5.0x | 0.34x | -69% LARGER | 1692 | 1043 |
| t5col:9 | t5col×20 | 684,062,545 | 29.6x | 2.00x | +83% smaller | 661 | 949 |
| mixed:none | mixed×20 | 2,510,019,665 | 8.1x | 0.54x | -50% LARGER | 1905 | 1069 |
| mixed:9 | mixed×20 | 609,822,888 | 33.2x | 2.24x | +106% smaller | 918 | 997 |

## Per file: best ternary-family variant (zstd L9) vs plain zstd L9 and binary bitpack (auto:9)

| file | plain zstd L9 (B) | auto:9 bitpack (B) | best ternary (B) | vs plain zstd | vs bitpack |
|---|---|---|---|---|---|
| 001 | 2,111 | 1,812 | mixed:9 1,708 | +24% | +6.09% |
| 002 | 11,656 | 2,990 | mixed:9 3,012 | +287% | -0.73% |
| 003 | 292,473,719 | 129,140,547 | mixed:9 129,361,141 | +126% | -0.17% |
| 004 | 155,699,988 | 70,249,943 | mixed:9 70,219,854 | +122% | +0.04% |
| 005 | 148,742,625 | 64,168,823 | mixed:9 64,201,538 | +132% | -0.05% |
| 006 | 15,025,724 | 7,493,401 | mixed:9 7,452,675 | +102% | +0.55% |
| 007 | 32,027,445 | 12,233,039 | mixed:9 12,250,225 | +161% | -0.14% |
| 008 | 231,484,596 | 137,223,364 | mixed:9 137,223,890 | +69% | -0.00% |
| 009 | 51,879,338 | 22,288,936 | mixed:9 22,300,129 | +133% | -0.05% |
| 010 | 42,872,827 | 16,365,900 | mixed:9 16,375,088 | +162% | -0.06% |
| 011 | 15,256,320 | 5,350,716 | mixed:9 5,365,346 | +184% | -0.27% |
| 012 | 1,852,063 | 664,957 | mixed:9 669,555 | +177% | -0.69% |
| 013 | 17,657 | 4,769 | mixed:9 4,765 | +271% | +0.08% |
| 014 | 11,812,868 | 3,920,118 | mixed:9 3,926,830 | +201% | -0.17% |
| 015 | 1,749 | 1,522 | mixed:9 1,421 | +23% | +7.11% |
| 016 | 53,261 | 33,566 | mixed:9 32,610 | +63% | +2.93% |
| 017 | 11,656 | 2,990 | mixed:9 3,012 | +287% | -0.73% |
| 018 | 48,820,957 | 26,952,171 | mixed:9 26,966,935 | +81% | -0.05% |
| 019 | 45,750,228 | 28,152,465 | mixed:9 28,191,641 | +62% | -0.14% |
| 020 | 182,929,313 | 85,590,473 | mixed:9 85,750,283 | +113% | -0.19% |
| 021 | 2,263,778 | 842,970 | mixed:9 850,453 | +166% | -0.88% |
| 022 | 26,548,724 | 16,298,162 | mixed:9 16,339,095 | +62% | -0.25% |
| 023 | 65,544,403 | 37,299,478 | mixed:9 37,363,205 | +75% | -0.17% |
| 024 | 52,826,813 | 22,833,398 | mixed:9 22,837,954 | +131% | -0.02% |
| 025 | 55,144,614 | 23,130,632 | mixed:9 23,136,816 | +138% | -0.03% |
| 026 | 54,672,911 | 22,937,316 | mixed:9 22,943,437 | +138% | -0.03% |
| 027 | 10,745,694 | 3,998,055 | mixed:9 4,008,385 | +168% | -0.26% |
| 028 | 84,989,074 | 47,770,027 | mixed:9 47,789,985 | +78% | -0.04% |
| 029 | 10,569,416 | 3,501,133 | mixed:9 3,503,090 | +202% | -0.06% |

Best ternary-family result larger than plain zstd L9 on 0/29 files, larger than bitpack on 23/29.
Pure ternary (t5 / t5row / t5col) larger than bitpack on 27/29 files.
