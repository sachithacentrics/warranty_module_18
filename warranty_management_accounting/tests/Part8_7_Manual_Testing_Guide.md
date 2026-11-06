# Part 8.7 Vendor Recovery: manual testing guide

Run after `warranty_management_mrf` 18.0.1.9.10 and `warranty_management_accounting` 18.0.1.6.1 are upgraded, with your approval.

**Don't change:** VCL/00006, WCAS/000049 or the unnumbered draft credit note of VCL/00006. Use a **new test claim** with accepted amount 100. Check the figures on the claim, the case's Warranty Cost tab, Warranty > Reports > Vendor Claim Recovery, and Warranty Cost.

| # | Step | Recovered | Outstanding |
|---|---|---|---|
| 1 | Vendor accepts 100 | 0 | 100 |
| 2 | Create Draft Credit Note, change its amount to 60 | 0 | 100 |
| 3 | Create Draft Credit Note again | Refused: a draft exists | |
| 4 | Post the note | 60 | 40; status Partial |
| 5 | Create Draft Credit Note | Draft of **40** | 40 |
| 6 | Post it | 100 | 0; status Recovered |
| 7 | Create Draft Credit Note again | Refused | |
| 8 | On a new claim: lower to 60, post, reverse for 15 | 45 | 55 |
| 9 | Reverse the remaining 45 | 0 | 100 |
| 10 | On a new claim: raise a draft to 500, post | 100, capped | 0 |
| 11 | Enter a credit note directly in Accounting for that vendor | No change: Finance reviews it | |

The allocation on the claim keeps showing the original 100 as history. Nothing is reconciled or paid automatically.
