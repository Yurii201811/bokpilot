# Accounting evidence register

Bokpilot does not enable a production posting account merely because a code or
name appears in source code. `AccountCatalog.get()` exposes only rows whose
evidence status is `approved` and whose source, reviewer, and review date are
all present. The synthetic approved catalog under `tests/fixtures/` is for
invariant tests only and is never a production default.

The current production entries remain disabled pending qualified review:

| Account | Swedish name | Source | Reviewer | Review date | Status |
| --- | --- | --- | --- | --- | --- |
| 1510 | Kundfordringar | https://www.bas.se/kontoplaner/ | — | — | pending_review |
| 1930 | Företagskonto | https://www.bas.se/kontoplaner/ | — | — | pending_review |
| 2440 | Leverantörsskulder | https://www.bas.se/kontoplaner/ | — | — | pending_review |
| 2611 | Utgående moms på försäljning inom Sverige, 25% | https://www.bas.se/kontoplaner/ | — | — | pending_review |
| 2641 | Ingående moms | https://www.bas.se/kontoplaner/ | — | — | pending_review |
| 3011 | Försäljning inom Sverige, 25% moms | https://www.bas.se/kontoplaner/ | — | — | pending_review |
| 3054 | Försäljning tjänster momsfri | https://www.bas.se/kontoplaner/ | — | — | pending_review |
| 5410 | Förbrukningsinventarier | https://www.bas.se/kontoplaner/ | — | — | pending_review |
| 5420 | Programvaror | https://www.bas.se/kontoplaner/ | — | — | pending_review |
| 5611 | Drivmedel för personbilar | https://www.bas.se/kontoplaner/ | — | — | pending_review |
| 5800 | Resekostnader | https://www.bas.se/kontoplaner/ | — | — | pending_review |
| 6071 | Representation, avdragsgill | https://www.bas.se/kontoplaner/ | — | — | pending_review |
| 6110 | Kontorsmateriel | https://www.bas.se/kontoplaner/ | — | — | pending_review |
| 6230 | Datakommunikation | https://www.bas.se/kontoplaner/ | — | — | pending_review |
| 6570 | Bankkostnader | https://www.bas.se/kontoplaner/ | — | — | pending_review |
| 6991 | Övriga externa kostnader, avdragsgilla | https://www.bas.se/kontoplaner/ | — | — | pending_review |
| 8410 | Räntekostnader för långfristiga skulder | https://www.bas.se/kontoplaner/ | — | — | pending_review |

Suggestion rules are likewise unresolved until their qualified-review status
is approved. A suggestion never creates journal lines; an explicit
`ReviewDecision` and an issue-free `PostingDraft` are separate requirements.

| Rule ID | Version | Source note | Qualified review status |
| --- | ---: | --- | --- |
| software-services | 1 | Existing Bokpilot heuristic | pending_review |
| telecom-connectivity | 1 | Existing Bokpilot heuristic | pending_review |
| office-supplies | 1 | Existing Bokpilot heuristic | pending_review |
| small-equipment | 1 | Existing Bokpilot heuristic | pending_review |
| bank-fees | 1 | Existing Bokpilot heuristic | pending_review |
| interest-expense | 1 | Existing Bokpilot heuristic | pending_review |
| business-travel | 1 | Existing Bokpilot heuristic | pending_review |
| meals-representation | 1 | Existing Bokpilot heuristic | pending_review |
| vehicle-fuel | 1 | Existing Bokpilot heuristic | pending_review |
