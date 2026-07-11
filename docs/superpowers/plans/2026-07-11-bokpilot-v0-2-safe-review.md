# Bokpilot v0.2 Safe Review Packets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a trustworthy, installable Bokpilot v0.2 that lets a Swedish small-business user import local source material, resolve ambiguous accounting facts, review an auditable posting draft, and download privacy-safe JSON, CSV, or validated SIE 4I packets without silent data loss.

**Architecture:** Keep the browser UI and dependency-light Python server, but separate source evidence, accounting suggestions, review decisions, posting drafts, and export batches. Replace the threaded JSON read/modify/write store with standard-library SQLite transactions, preserve source files by hash, and make every approval pass explicit validation gates. Package all runtime assets inside the Python wheel and keep the application loopback-only.

**Tech Stack:** Python 3.10-3.14 standard library (`dataclasses`, `decimal`, `sqlite3`, `http.server`, `importlib.resources`), semantic HTML, CSS, vanilla JavaScript, `unittest`, GitHub Actions.

## Global Constraints

- Runtime dependencies remain Python standard-library only for v0.2; development-only tools must not be required to run Bokpilot.
- The supported network boundary is loopback (`127.0.0.1` or `::1`) only. Remote hosting, user accounts, and multi-user permissions are outside v0.2.
- Bokpilot remains a pre-accounting assistant: no live posting, VAT filing, payment initiation, client messaging, or autonomous approval.
- Unknown transaction purpose, unsupported currency, invalid dates, inconsistent VAT, unbalanced lines, and unresolved duplicate warnings block approval.
- Store monetary values as integer minor units plus ISO currency; never persist or export accounting money as binary floating-point.
- Preserve imported source evidence and original suggestions. Reviewer changes create new records; they never overwrite the originals.
- Default exports exclude raw document text and local attachment paths.
- Do not bundle a complete BAS account dataset until its redistribution terms are confirmed. v0.2 may ship a source-documented curated subset and support user-supplied account catalogs later.
- SIE output targets import-oriented SIE type 4I under the current SIE 1-4 specification, declares `PC8`, and is actually encoded as CP437. It stays labelled experimental until the official SIE test service accepts the synthetic fixture.
- Each accounting rule must have a stable rule ID, version, source note, and qualified-review status. Unreviewed rules remain disabled or produce an unresolved suggestion.
- Every task begins with a failing test, ends with focused and broad verification, and creates one reviewable commit only after the recovered repository passes `git fsck`.

---

## Baseline and Decision

### Verified baseline on 2026-07-11

- Canonical checkout: `/Users/yuriibakurov/Documents/Second Open Source Project`.
- Active branch/HEAD: `codex/csv-import-review-safety` at `2486a26742f3f87e5c4c509824fb87025a2cc216`.
- Working tree was clean before this plan file was created.
- All 19 existing tests passed; `compileall`, `node --check static/app.js`, and `git diff --check` passed.
- The checkout is not Git-healthy: `git fsck --full --no-reflogs` reports 22 iCloud placeholder object files, four reachable missing trees, four broken links, and two invalid index cache-tree pointers. Some diffs, archives, and format-patch operations fail.
- Public `origin/main` is `ccdaf7d` and contains green CI, while the current branch contains five local behavior commits not present on the public branch. There is no open PR, issue, tag, or release.
- A built wheel contains Python modules but no `static/` or `samples/` assets, so the advertised installed application cannot serve its UI or load demo data.
- Confirmed unsafe behaviors include: arbitrary account `NOT-BAS` plus `999%` VAT can be approved; foreign-currency input receives SEK postings without a warning; malformed dates can pass; ambiguous positive bank rows become 25% VAT sales; sample loading and reset can erase the workspace without confirmation.

### Approaches considered

1. **Trust-first v0.2 (recommended):** repair the repository, fix package/runtime correctness, introduce exact domain types and approval gates, migrate to SQLite, then improve import/review/export UX. This is the smallest route to a version suitable for real local testing.
2. **Polish-only v0.1.1:** improve styling, downloads, and documentation while retaining the current model and JSON store. This is faster, but it leaves confirmed accounting, concurrency, packaging, and data-loss defects in place.
3. **Integration-first:** add OCR, AI, Fortnox, Visma, or Bokio adapters now. This increases privacy, authentication, and accounting risk before the local core is trustworthy, so it is deferred.

### Release slices

- **Recovery checkpoint:** Git-healthy reconstructed branch with remote CI and all five local improvements preserved.
- **Foundation checkpoint:** installable wheel, strict input/domain model, accounting invariants, and safe local persistence.
- **Workflow checkpoint:** preview/commit import, provenance, matching, auditable review, and actual downloads.
- **v0.2 release candidate:** validated SIE 4I fixture, accessible responsive UI, green CI, updated safety docs, and an accountant-reviewed enabled rule set.

This master plan contains four sequential subprojects: Tasks 0-1 recovery/foundation, Tasks 2-4 trust core, Tasks 5-6 review workflow, and Tasks 7-9 release. Close and review each subproject before starting the next; do not implement them in parallel because their schema and API contracts are shared.

### External standards and policy inputs

- [SIE-Gruppen's current SIE 1-4 specification, edition 4C](https://sie.se/wp-content/uploads/2026/02/SIE_filformat_ver_4C_2025-08-06.pdf) defines the type 4I records and PC8 encoding; its official test service is the release validator for synthetic fixtures.
- [BAS publishes the 2026 account plans](https://www.bas.se/kontoplaner/), while [the official machine-readable 2026 JSON is a paid product](https://www.bas.se/kontoplaner/kontoplanen-i-maskinlasbart-format/). The project therefore needs a licensing check before redistributing a complete catalog.
- [Skatteverket's bookkeeping guidance](https://www.skatteverket.se/foretag/drivaforetag/bokforingochbokslut/bokforingvadkraverlagen.4.18e1b10334ebe8bc80005195.html) emphasizes source records, seven-year retention, and protecting digitized information from change or loss. Bokpilot must explain that its backup feature supports—but does not itself guarantee—the user's legal archive duty.

## Planned File Structure

```text
bokpilot/
  __init__.py                 Single version source.
  accounts.py                 Curated, source-documented account catalog.
  accounting.py               Posting-draft construction and balance invariants.
  domain.py                   Exact money, enums, source records, decisions, and drafts.
  exports.py                  Privacy-safe JSON/CSV export batches.
  imports.py                  Preview, row diagnostics, commit, and source fingerprints.
  matching.py                 Explainable bank-to-document match suggestions.
  migrations.py               Explicit JSON-to-SQLite and schema migrations.
  models.py                   v0.1 compatibility re-exports for domain types.
  parsers.py                  Strict CSV, money, date, and text extraction.
  repository.py               SQLite transactions and query APIs.
  review.py                   Approval policy and immutable review revisions.
  rules.py                    Versioned, token-aware suggestion rules only.
  security.py                 HTTP origin/token/header/body-limit policy.
  serialization.py            v1/v2 workspace compatibility codecs.
  server.py                   Routes and static/download responses.
  sie.py                      CP437 SIE 4I serializer and validator checks.
  store.py                    v0.1 compatibility wrapper around Repository.
  resources/
    static/{index.html,styles.css,app.js}
    samples/bank/bank-transactions.csv
    samples/invoices/customer-invoice-web-design.txt
    samples/invoices/supplier-invoice-openai.txt
    samples/receipts/pressbyran-office-supplies.txt
    samples/receipts/tele2-broadband.txt
tests/
  helpers.py
  test_accounts.py
  test_accounting.py
  test_domain.py
  test_exports.py
  test_imports.py
  test_matching.py
  test_migrations.py
  test_packaging.py
  test_parsers.py
  test_repository.py
  test_review.py
  test_security.py
  test_serialization.py
  test_server_api.py
  test_sie.py
docs/
  accounting-evidence.md
  backup-and-restore.md
  release-checklist.md
scripts/
  smoke_installed.py
```

---

### Task 0: Recover Git Integrity and Reconcile the Baseline

**Files:**

- Preserve read-only: `/Users/yuriibakurov/Documents/Second Open Source Project`
- Create during execution: `/Users/yuriibakurov/Mac Work/Local Documents/bokpilot-v0.2-recovery`
- Compare/recover: `README.md`, `bokpilot/exports.py`, `bokpilot/parsers.py`, `bokpilot/server.py`, `docs/data-model.md`, `examples/exports/README.md`, `examples/exports/sample-approved-export.csv`, `tests/test_parsers.py`, `tests/test_server_api.py`, `tests/test_store_exports.py`
- Copy this plan: `docs/superpowers/plans/2026-07-11-bokpilot-v0-2-safe-review.md`
- Retain from remote: `.github/workflows/ci.yml`

**Interfaces:**

- Consumes: damaged clean working tree at `2486a26` and public `origin/main` at `ccdaf7d`.
- Produces: a Git-healthy `codex/v0-2-safe-review` branch whose files preserve the five local behavior commits plus remote CI.

- [ ] **Step 1: Make a byte-for-byte safety copy before recovery**

Run:

```bash
source='/Users/yuriibakurov/Documents/Second Open Source Project'
backup='/Users/yuriibakurov/Mac Work/Local Documents/bokpilot-damaged-20260711-backup'
test ! -e "$backup"
ditto "$source" "$backup"
```

Expected: the backup exists, and the original checkout remains untouched.

- [ ] **Step 2: Create a healthy clone from the public source**

Run:

```bash
target='/Users/yuriibakurov/Mac Work/Local Documents/bokpilot-v0.2-recovery'
test ! -e "$target"
git clone https://github.com/Yurii201811/bokpilot.git "$target"
git -C "$target" switch -c codex/v0-2-safe-review
git -C "$target" fsck --full --no-reflogs
git -C "$target" archive HEAD >/dev/null
```

Expected: both integrity commands exit `0`.

- [ ] **Step 3: Produce a filesystem comparison that does not depend on damaged Git history**

Run:

```bash
diff -ruN \
  --exclude=.git \
  --exclude=__pycache__ \
  --exclude='*.pyc' \
  --exclude=data \
  '/Users/yuriibakurov/Mac Work/Local Documents/bokpilot-v0.2-recovery' \
  '/Users/yuriibakurov/Documents/Second Open Source Project' \
  > /tmp/bokpilot-recovery-review.patch || test $? -eq 1
```

Expected: the patch shows only the known local source/test/docs changes and this plan; it must not contain secrets, workspace data, or `.git` objects.

- [ ] **Step 4: Recover the known local behavior files into the healthy clone**

Run this exact allowlisted copy:

```bash
SOURCE='/Users/yuriibakurov/Documents/Second Open Source Project'
TARGET='/Users/yuriibakurov/Mac Work/Local Documents/bokpilot-v0.2-recovery'
for path in \
  README.md \
  bokpilot/exports.py \
  bokpilot/parsers.py \
  bokpilot/server.py \
  docs/data-model.md \
  docs/superpowers/plans/2026-07-11-bokpilot-v0-2-safe-review.md \
  examples/exports/README.md \
  examples/exports/sample-approved-export.csv \
  tests/test_parsers.py \
  tests/test_server_api.py \
  tests/test_store_exports.py
do
  mkdir -p "$TARGET/$(dirname "$path")"
  ditto "$SOURCE/$path" "$TARGET/$path"
done
```

Then run:

```bash
cd '/Users/yuriibakurov/Mac Work/Local Documents/bokpilot-v0.2-recovery'
python3 -m unittest -v
python3 -m compileall -q bokpilot tests
node --check static/app.js
git diff --check
```

Expected: 19 tests pass and all other commands exit `0`.

- [ ] **Step 5: Record provenance for the recovered local work**

Create the commit with the five original local SHAs in its body:

```bash
git add README.md bokpilot docs/data-model.md docs/superpowers/plans/2026-07-11-bokpilot-v0-2-safe-review.md examples/exports tests
git commit -m "feat: recover CSV import safety improvements" \
  -m "Recovered from 2989a21, d0df69d, 8755b1c, 87df596, and 2486a26 after iCloud object eviction."
```

Expected: the commit succeeds; do not push or delete the damaged checkout.

- [ ] **Step 6: Re-run the recovery gate**

Run:

```bash
git fsck --full --no-reflogs
git archive HEAD >/dev/null
git status --short --branch
git log --oneline --decorate -5
```

Expected: both integrity checks exit `0`, and the branch is clean.

---

### Task 1: Make the Installed Package Fully Runnable

**Files:**

- Move: `static/index.html` -> `bokpilot/resources/static/index.html`
- Move: `static/styles.css` -> `bokpilot/resources/static/styles.css`
- Move: `static/app.js` -> `bokpilot/resources/static/app.js`
- Move: `samples/bank/bank-transactions.csv` -> `bokpilot/resources/samples/bank/bank-transactions.csv`
- Move: `samples/invoices/customer-invoice-web-design.txt` -> `bokpilot/resources/samples/invoices/customer-invoice-web-design.txt`
- Move: `samples/invoices/supplier-invoice-openai.txt` -> `bokpilot/resources/samples/invoices/supplier-invoice-openai.txt`
- Move: `samples/receipts/pressbyran-office-supplies.txt` -> `bokpilot/resources/samples/receipts/pressbyran-office-supplies.txt`
- Move: `samples/receipts/tele2-broadband.txt` -> `bokpilot/resources/samples/receipts/tele2-broadband.txt`
- Create: `bokpilot/resources.py`
- Create: `tests/test_packaging.py`
- Create: `scripts/smoke_installed.py`
- Modify: `bokpilot/sample_data.py`
- Modify: `bokpilot/server.py`
- Modify: `pyproject.toml`
- Modify: `README.md`

**Interfaces:**

- Consumes: package name `bokpilot` and the existing three static assets/sample fixtures.
- Produces: `resource_file(*parts) -> Traversable`, an installed-wheel HTTP smoke command, and one package-contained source of runtime assets.

- [ ] **Step 1: Write failing package-resource tests**

Add to `tests/test_packaging.py`:

```python
import unittest
from importlib.resources import files


class PackagingTest(unittest.TestCase):
    def test_runtime_assets_are_inside_package(self):
        root = files("bokpilot").joinpath("resources")
        self.assertTrue(root.joinpath("static", "index.html").is_file())
        self.assertTrue(root.joinpath("static", "app.js").is_file())
        self.assertTrue(root.joinpath("static", "styles.css").is_file())
        self.assertTrue(root.joinpath("samples", "bank", "bank-transactions.csv").is_file())
```

- [ ] **Step 2: Run the test and confirm the current package layout fails**

Run: `python3 -m unittest tests.test_packaging -v`

Expected: FAIL because `bokpilot/resources` does not exist.

- [ ] **Step 3: Move assets and add a resource interface**

Use `git mv` for every asset listed in the task's **Files** block, then implement `bokpilot/resources.py`:

```python
from importlib.resources import files
from importlib.resources.abc import Traversable


def resource_file(*parts: str) -> Traversable:
    target = files("bokpilot").joinpath("resources", *parts)
    if not target.is_file():
        raise FileNotFoundError("Packaged Bokpilot resource was not found.")
    return target
```

Update `sample_data.py` to read through `resource_file`, and change static serving to an allowlist of `index.html`, `app.js`, and `styles.css` using the same interface. Do not convert a user URL directly into a filesystem path.

- [ ] **Step 4: Configure wheel package data**

Set in `pyproject.toml`:

```toml
[tool.setuptools]
packages = ["bokpilot"]
include-package-data = true

[tool.setuptools.package-data]
bokpilot = [
  "resources/static/*",
  "resources/samples/bank/*.csv",
  "resources/samples/invoices/*.txt",
  "resources/samples/receipts/*.txt",
]
```

- [ ] **Step 5: Add an installed-wheel smoke script**

Implement `scripts/smoke_installed.py` with this interface:

```python
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from urllib.request import Request, urlopen

from bokpilot.server import make_server
from bokpilot.store import WorkspaceStore


def request(url: str, *, body: bytes | None = None) -> tuple[int, bytes]:
    headers = {"Content-Type": "application/json"} if body is not None else {}
    method = "POST" if body is not None else "GET"
    with urlopen(Request(url, data=body, headers=headers, method=method), timeout=5) as response:
        return response.status, response.read()


def smoke() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = WorkspaceStore(Path(directory) / "workspace.json")
        server = make_server("127.0.0.1", 0, store)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address
        base = f"http://{host}:{port}"
        try:
            for path in ("/", "/app.js", "/styles.css"):
                status, payload = request(base + path)
                if status != 200 or not payload:
                    raise RuntimeError(f"Installed asset smoke failed for {path}.")
            status, payload = request(base + "/api/load-sample", body=b"{}")
            workspace = json.loads(payload.decode("utf-8"))
            if status != 200 or len(workspace["items"]) < 10:
                raise RuntimeError("Installed sample-data smoke failed.")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


def build_wheel_and_smoke() -> None:
    project = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        wheelhouse = root / "wheelhouse"
        environment = root / "venv"
        wheelhouse.mkdir()
        subprocess.run(
            [sys.executable, "-m", "pip", "wheel", str(project), "--no-deps", "--wheel-dir", str(wheelhouse)],
            check=True,
        )
        subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
        python = environment / "bin" / "python"
        wheel = next(wheelhouse.glob("bokpilot-*.whl"))
        subprocess.run([str(python), "-m", "pip", "install", str(wheel)], check=True)
        subprocess.run([str(python), str(Path(__file__).resolve())], cwd="/tmp", check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-wheel", action="store_true")
    arguments = parser.parse_args()
    build_wheel_and_smoke() if arguments.build_wheel else smoke()
```

Task 6 updates the request helper to fetch and send the session token after the HTTP boundary is added.

- [ ] **Step 6: Build and test outside the checkout**

Run:

```bash
WHEELHOUSE=$(mktemp -d)
WHEEL_VENV=$(mktemp -d)
python3 -m pip wheel . --no-deps --wheel-dir "$WHEELHOUSE"
python3 -m venv "$WHEEL_VENV"
"$WHEEL_VENV/bin/python" -m pip install "$WHEELHOUSE"/bokpilot-*.whl
cd /tmp
"$WHEEL_VENV/bin/python" \
  '/Users/yuriibakurov/Mac Work/Local Documents/bokpilot-v0.2-recovery/scripts/smoke_installed.py'
```

Expected: the clean environment serves all assets and loads samples without referring to the source checkout.

- [ ] **Step 7: Run broad checks and commit**

Run:

```bash
python3 -m unittest -v
python3 -m compileall -q bokpilot tests
git diff --check
git add -A -- bokpilot static samples pyproject.toml README.md tests/test_packaging.py scripts/smoke_installed.py
git commit -m "fix: package Bokpilot runtime assets"
```

---

### Task 2: Introduce Exact Domain Types and Strict Parsing

**Files:**

- Create: `bokpilot/domain.py`
- Create: `bokpilot/serialization.py`
- Create: `tests/test_domain.py`
- Create: `tests/test_serialization.py`
- Create: `tests/fixtures/workspaces/v1-workspace.json`
- Modify: `bokpilot/exports.py`
- Modify: `bokpilot/models.py`
- Modify: `bokpilot/parsers.py`
- Modify: `bokpilot/rules.py`
- Modify: `bokpilot/server.py`
- Modify: `bokpilot/store.py`
- Modify: `bokpilot/resources/static/app.js`
- Modify: `tests/test_parsers.py`
- Modify: `tests/test_rules.py`
- Modify: `tests/test_server_api.py`
- Modify: `tests/test_store_exports.py`
- Modify: `docs/data-model.md`

**Interfaces:**

- Produces: `Money(minor: int, currency: str)`, `VatTreatment`, `SourceKind`, `EvidenceStatus`, `TransactionNature`, `AccountingMethod`, `CompanyProfile`, `SourceRecord`, `JournalLine`, `Suggestion`, v1/v2 serialization codecs, `parse_money(value, locale) -> Money`, and `parse_date(value) -> date`.
- Consumes: raw CSV/text/manual strings only; no floats cross the parser boundary.

- [ ] **Step 1: Write failing exactness and validation tests**

Add cases that require:

```python
self.assertEqual(parse_money("1 248,75 SEK", "sv-SE").minor, 124875)
self.assertEqual(parse_money("1,248.75", "en-US").minor, 124875)
with self.assertRaises(ValueError):
    parse_money("1,234", "auto")
with self.assertRaises(ValueError):
    parse_money("abc123xyz", "sv-SE")
with self.assertRaises(ValueError):
    parse_date("2026-99-99")
with self.assertRaises(ValueError):
    parse_date("")
```

Also assert that `Money(-24900, "SEK").to_dict()` is `{"minor": -24900, "currency": "SEK"}` and survives JSON round-trip exactly.

- [ ] **Step 2: Run focused tests and verify the known failures**

Run: `python3 -m unittest tests.test_domain tests.test_serialization tests.test_parsers -v`

Expected: FAIL on missing types, malformed-date acceptance, and permissive money parsing.

- [ ] **Step 3: Implement exact money and accounting enums**

Use these public definitions in `bokpilot/domain.py`:

```python
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any


class VatTreatment(str, Enum):
    UNKNOWN = "unknown"
    EXEMPT = "exempt"
    RATE_0 = "0"
    RATE_6 = "6"
    RATE_12 = "12"
    RATE_25 = "25"


class SourceKind(str, Enum):
    BANK_TRANSACTION = "bank_transaction"
    RECEIPT = "receipt"
    SUPPLIER_INVOICE = "supplier_invoice"
    CUSTOMER_INVOICE = "customer_invoice"
    MANUAL = "manual"


class EvidenceStatus(str, Enum):
    AVAILABLE = "available"
    MANUAL_ATTESTED = "manual_attested"
    LEGACY_UNAVAILABLE = "legacy_unavailable"


class TransactionNature(str, Enum):
    UNKNOWN = "unknown"
    EXPENSE = "expense"
    REVENUE = "revenue"
    TRANSFER = "transfer"
    OWNER_MOVEMENT = "owner_movement"
    REFUND = "refund"
    LOAN = "loan"


class AccountingMethod(str, Enum):
    CASH = "cash"
    ACCRUAL = "accrual"


@dataclass(frozen=True)
class Money:
    minor: int
    currency: str = "SEK"

    def __post_init__(self) -> None:
        if type(self.minor) is not int:
            raise TypeError("Money.minor must be an integer.")
        normalized = self.currency.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("Currency must be a three-letter ISO code.")
        object.__setattr__(self, "currency", normalized)

    @classmethod
    def from_major(cls, value: str | int | Decimal, currency: str = "SEK") -> "Money":
        scaled = Decimal(str(value)) * 100
        if scaled != scaled.to_integral_value():
            raise ValueError("Money supports at most two decimal places.")
        return cls(int(scaled), currency)

    def to_dict(self) -> dict[str, Any]:
        return {"minor": self.minor, "currency": self.currency}
```

Add the exact source boundary:

```python
from dataclasses import field
from typing import Mapping


@dataclass(frozen=True)
class SourceRecord:
    id: str
    kind: SourceKind
    occurred_on: date
    amount: Money
    description: str
    counterparty: str
    source_filename: str
    source_row: int | None
    import_key: str
    attachment_sha256: str | None
    evidence_status: EvidenceStatus
    extracted: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CompanyProfile:
    name: str
    accounting_method: AccountingMethod
    fiscal_year_start: date
    fiscal_year_end: date
    currency: str
    voucher_series: str
    organization_number: str | None = None


@dataclass(frozen=True)
class JournalLine:
    account: str
    account_name: str
    debit_minor: int = 0
    credit_minor: int = 0

    def __post_init__(self) -> None:
        if self.debit_minor < 0 or self.credit_minor < 0:
            raise ValueError("Journal amounts cannot be negative.")
        if self.debit_minor and self.credit_minor:
            raise ValueError("A journal line cannot be both debit and credit.")


@dataclass(frozen=True)
class Suggestion:
    nature: TransactionNature
    category: str
    account: str | None
    account_name: str | None
    vat: VatTreatment
    vat_minor: int | None
    confidence: float
    explanation: str
    risk_flags: tuple[str, ...]
    rule_id: str | None
    rule_version: int | None
```

Keep the original input string in provenance metadata when useful, but do not use it for calculations.

- [ ] **Step 4: Replace regex-only dates with calendar validation**

Normalize the supported date layouts and finish with `date.fromisoformat(normalized)`. Missing dates must produce a row/document issue, never today's date.

- [ ] **Step 5: Implement strict locale-aware money parsing**

Accept only documented Swedish, English, and plain layouts. If `locale="auto"` matches more than one interpretation, raise `ValueError("Ambiguous money format; choose the source locale.")`. Parenthesized negatives remain supported.

- [ ] **Step 6: Remove float serialization from accounting values**

Replace `money_to_json`, parser output, VAT amounts, and journal amounts with integer minor-unit fields. Confidence may remain a float because it is not money. Update the store, rules, exports, API, frontend formatters, tests, data model, and examples in this same task so the broad suite remains green.

Add `decode_source(payload)` and `encode_source(record)` in `bokpilot/serialization.py`. `decode_source` accepts both v2 `amount_minor` and legacy v1 `amount`; v1 numbers are converted with `Money.from_major(Decimal(str(value)), currency)`. `encode_source` always writes schema-v2 fields `amount_minor` and `currency`. Apply the same compatibility rule to VAT and journal-line amounts. No caller receives a `Money` object where it still expects a dictionary.

The JavaScript formatter uses `Number(raw.amount_minor) / 100`. API regression tests assert integer minor units, while `tests/fixtures/workspaces/v1-workspace.json` retains legacy numeric fields to prove read compatibility.

- [ ] **Step 7: Run focused and broad checks, then commit**

Run:

```bash
python3 -m unittest tests.test_domain tests.test_serialization tests.test_parsers -v
python3 -m unittest -v
python3 -m compileall -q bokpilot tests
node --check bokpilot/resources/static/app.js
git diff --check
git add bokpilot/domain.py bokpilot/serialization.py bokpilot/exports.py bokpilot/models.py bokpilot/parsers.py bokpilot/rules.py bokpilot/server.py bokpilot/store.py bokpilot/resources/static/app.js tests docs/data-model.md
git commit -m "refactor: make accounting inputs exact and validated"
```

---

### Task 3: Separate Suggestions from Accounting Posting Decisions

**Files:**

- Create: `bokpilot/accounting.py`
- Create: `bokpilot/accounts.py`
- Create: `docs/accounting-evidence.md`
- Create: `tests/helpers.py`
- Create: `tests/fixtures/accounts/approved-test-catalog.json`
- Create: `tests/test_accounts.py`
- Create: `tests/test_accounting.py`
- Modify: `bokpilot/models.py`
- Modify: `bokpilot/rules.py`
- Modify: `tests/test_rules.py`

**Interfaces:**

- Consumes: `SourceRecord` and an explicit `ReviewDecision`.
- Produces: `AccountCatalog`, `suggest(record) -> Suggestion`, `build_posting(record, decision, profile, catalog) -> PostingDraft`, and `posting_issues(draft) -> tuple[str, ...]`.
- Rule output never mutates source evidence and never becomes exportable without a separate review decision.

- [ ] **Step 1: Write failing accounting-safety scenarios**

Cover these exact outcomes:

Create `tests.helpers.source_record(description, minor, kind=SourceKind.BANK_TRANSACTION)`, `tests.helpers.company_profile()`, and `tests.helpers.approved_test_catalog()`. The test catalog is loaded only from `tests/fixtures/accounts/approved-test-catalog.json`, marks its synthetic entries approved, and is never the production default. Every test uses a stable import key, a 2026-07-11 source date, a 2026 calendar fiscal year, currency `SEK`, cash accounting, and voucher series `BP`. Then assert:

```python
owner = source_record("Owner deposit", 100_000)
transfer = source_record("Transfer savings", 100_000)
unmatched = source_record("Unmatched vendor", -10_000)
unknown = source_record("Unknown purchase", -10_000)

self.assertEqual(suggest(owner).nature, TransactionNature.UNKNOWN)
self.assertEqual(suggest(transfer).vat, VatTreatment.UNKNOWN)
self.assertEqual(suggest(unmatched).category, "Unclassified expense")
self.assertEqual(suggest(unknown).vat, VatTreatment.UNKNOWN)

invalid_account = build_posting(
    unknown,
    ReviewDecision(TransactionNature.EXPENSE, "NOT-BAS", VatTreatment.RATE_25, 2_000, "Synthetic test", True),
    company_profile(),
    approved_test_catalog(),
)
self.assertIn("invalid_account", invalid_account.issues)
```

The `VatTreatment` enum makes `999` unrepresentable; API validation for the raw string is covered in Task 6.

Add scenario tests for customer invoice, supplier invoice, matched bank payment, cash method, accrual method, partial payment, `VatTreatment.RATE_0` override with explicit source VAT, and debit/credit equality.

- [ ] **Step 2: Verify current rules fail the scenarios**

Run: `python3 -m unittest tests.test_accounting tests.test_rules -v`

Expected: FAIL because amount sign currently determines income and unknown expenses assume 25% VAT.

- [ ] **Step 3: Make rules token-aware and suggestion-only**

Give every rule `rule_id`, `version`, `keywords`, `phrases`, `suggested_nature`, `suggested_account`, `suggested_vat`, `confidence`, and `evidence_status`. Match whole normalized tokens and bounded phrases; the token `mat` must not match `unmatched`. If no reviewed rule matches, return `UNKNOWN` nature and `UNKNOWN` VAT without journal lines.

Create `AccountCatalog` from the project's existing curated accounts plus receivables `1510` and payables `2440`. Each production account entry includes code, Swedish name, source URL, evidence status, reviewer, and review date and defaults to `pending_review`. `AccountCatalog.get(code)` returns an enabled account only when its evidence status is `approved`; no fallback account name is invented. Tests inject the explicitly synthetic approved catalog so posting invariants can be exercised before the manual Task 9 review gate.

- [ ] **Step 4: Implement explicit review decisions and posting drafts**

Define:

```python
@dataclass(frozen=True)
class ReviewDecision:
    nature: TransactionNature
    account: str
    vat: VatTreatment
    vat_minor: int | None
    reviewer_note: str
    risk_acknowledged: bool


@dataclass(frozen=True)
class PostingDraft:
    source_id: str
    lines: tuple[JournalLine, ...]
    rule_id: str | None
    rule_version: int | None
    issues: tuple[str, ...]
```

Validate account format and membership in the configured curated catalog. Preserve source VAT separately from reviewer-selected VAT. A changed VAT rate must either calculate a new VAT amount from gross or use an explicit reviewer-entered amount; it must never silently reuse an inconsistent source amount.

- [ ] **Step 5: Add source-kind and accounting-method postings**

Use bank account `1930` only for bank movements. Use receivables/payables accounts only in reviewed invoice scenarios, and test both cash and accrual profiles. Do not enable any mapping until its evidence row in `docs/accounting-evidence.md` has source, reviewer, review date, and status `approved`.

- [ ] **Step 6: Enforce posting invariants**

`posting_issues` must report unsupported currency, unknown nature/VAT, invalid account, VAT exceeding gross, missing risk acknowledgement, missing note for high-risk categories, and any non-zero debit/credit difference. Approval accepts only an empty issue tuple.

- [ ] **Step 7: Run checks and commit**

Run:

```bash
python3 -m unittest tests.test_accounts tests.test_accounting tests.test_rules -v
python3 -m unittest -v
git diff --check
git add bokpilot/accounts.py bokpilot/accounting.py bokpilot/models.py bokpilot/rules.py tests docs/accounting-evidence.md
git commit -m "feat: gate posting drafts on explicit accounting decisions"
```

---

### Task 4: Replace JSON Mutation with Private Transactional SQLite Storage

**Files:**

- Create: `bokpilot/repository.py`
- Create: `bokpilot/migrations.py`
- Create: `tests/test_repository.py`
- Create: `tests/test_migrations.py`
- Modify: `bokpilot/store.py` (v0.1 compatibility wrapper retained through v0.2)
- Modify: `bokpilot/server.py`
- Modify: `scripts/smoke_installed.py`
- Modify: `docs/architecture.md`
- Modify: `docs/data-model.md`

**Interfaces:**

- Produces: `Repository(path)`, `Repository.transaction()`, `workspace_revision`, `import_sources`, `get_source`, `list_review_queue`, `append_review`, `save_posting_draft`, `create_export_batch`, `backup_to`, `restore_from`, and explicit `migrate_json_workspace`.
- Database schema version: `2`, tracked with `PRAGMA user_version`.

- [ ] **Step 1: Write failing concurrency, privacy, and recovery tests**

Tests must assert:

- 40 concurrent inserts retain exactly 40 unique rows with no exception.
- a failed transaction leaves the previous committed state readable.
- database and attachment files are created with mode `0600`; their directories use `0700`.
- mandatory import-key lookup uses a unique index, including records whose source row is absent.
- JSON migration keeps the original JSON unchanged, writes a timestamped backup, and is idempotent.
- a backup bundle contains a consistent SQLite snapshot, every referenced attachment and export artifact, and a manifest of paths, byte counts, and SHA-256 values.
- restoring a verified bundle into a new data directory reproduces row counts, attachment hashes, and export checksums; a hash mismatch aborts without changing the destination.
- list queries paginate deterministically by `(occurred_on, id)`.
- the single workspace revision starts at `0`, increments exactly once in every successful mutation transaction, and remains unchanged after rollback.

- [ ] **Step 2: Run tests and confirm JSON storage fails the concurrency gate**

Run: `python3 -m unittest tests.test_repository tests.test_migrations -v`

Expected: FAIL before the repository exists.

- [ ] **Step 3: Create the SQLite schema in one transaction**

Create tables for `workspace_state`, `company_profile`, `sources`, `source_attachments`, `suggestions`, `reviews`, `posting_drafts`, `import_batches`, `duplicate_candidates`, `duplicate_decisions`, `matches`, and `export_batches`. `workspace_state` has exactly one row `(id=1, revision INTEGER NOT NULL)` initialized to `0`. Use foreign keys, immutable created timestamps, integer minor amounts, JSON only for non-queryable snapshots, and these indexes:

```sql
CREATE UNIQUE INDEX source_import_key_uq
ON sources(import_key);

CREATE INDEX review_queue_idx
ON sources(status, occurred_on, id);

CREATE INDEX matches_source_idx
ON matches(source_id, status);
```

- [ ] **Step 4: Configure safe connections and transactions**

Each operation opens a bounded connection with `timeout=5.0`, enables `PRAGMA foreign_keys=ON`, sets a busy timeout, and uses an explicit transaction. Apply `chmod(0o700)` to the data/attachment directories and `chmod(0o600)` to created files.

Every successful mutation ends with `UPDATE workspace_state SET revision = revision + 1 WHERE id = 1` inside the same transaction and returns the new value. `GET /api/workspace` includes top-level `revision`; failed or rolled-back mutations do not increment it.

Update the installed smoke to use `bokpilot.sqlite3` in its temporary directory and inject the repository compatibility wrapper expected by `make_server`.

Expose `backup_to(destination: Path, attachment_root: Path, export_root: Path) -> BackupReport` and `restore_from(backup: Path, destination_root: Path, expected_sha256: str) -> RestoreReport`. `backup_to` uses SQLite's backup API for a consistent database snapshot, copies every referenced attachment and export artifact into a temporary ZIP bundle with `ZIP_STORED`, writes `manifest.json`, verifies all member hashes, then atomically renames the completed `.bokpilot-backup` file. Restore rejects absolute or parent-traversal ZIP members, verifies the outer and manifest checksums, runs `PRAGMA integrity_check`, and only atomically installs into a new or explicitly empty destination root.

- [ ] **Step 5: Implement explicit JSON migration**

Expose `migrate_json_workspace(source: Path, destination: Path) -> MigrationReport`.

The report contains source SHA-256, backup path, migrated item/event counts, skipped count, and schema version. Never delete or rewrite `source`. Re-running with the same source hash returns the prior report without duplicating rows.

Legacy v0.1 workspaces do not contain complete original file bytes. Give each migrated record the deterministic key `f"legacy-v1:{workspace_sha256}:{item_id}"`, migrate its extracted fields and any retained `document_text`, set `attachment_sha256` to `None`, set evidence status `legacy_unavailable`, and add a review issue. Do not fabricate an original-file hash or claim archival completeness.

- [ ] **Step 6: Add a CLI migration command**

Support:

```bash
python3 -m bokpilot migrate \
  --from-json ./data/workspace.json \
  --to-sqlite ./data/bokpilot.sqlite3
```

Expected: a human-readable report and exit `0`; invalid/corrupt JSON exits non-zero without changing the destination.

Also support:

```bash
python3 -m bokpilot backup --to ./backups/bokpilot-20260711.bokpilot-backup
BACKUP_SHA256=$(shasum -a 256 ./backups/bokpilot-20260711.bokpilot-backup | awk '{print $1}')
python3 -m bokpilot restore \
  --from ./backups/bokpilot-20260711.bokpilot-backup \
  --to ./data/restored-bokpilot \
  --sha256 "$BACKUP_SHA256"
```

Expected: backup prints its SHA-256; restore refuses an incorrect checksum or an existing non-empty destination.

- [ ] **Step 7: Verify indexed scaling without a flaky wall-clock assertion**

Add a test importing 10,000 synthetic rows in one transaction and returning a 100-row page without materializing all records. Assert through `EXPLAIN QUERY PLAN` that the queue and idempotency queries use `review_queue_idx` and `source_import_key_uq`. Record the development-Mac elapsed time as non-gating benchmark output; CI correctness does not depend on a machine-specific duration.

- [ ] **Step 8: Run checks and commit**

Run:

```bash
python3 -m unittest tests.test_repository tests.test_migrations -v
python3 -m unittest -v
python3 -m compileall -q bokpilot tests
git diff --check
git add bokpilot/repository.py bokpilot/migrations.py bokpilot/store.py bokpilot/server.py scripts/smoke_installed.py tests docs
git commit -m "feat: add transactional local workspace storage"
```

---

### Task 5: Add Previewed, Idempotent Imports and Explainable Matching

**Files:**

- Create: `bokpilot/imports.py`
- Create: `bokpilot/matching.py`
- Create: `tests/test_imports.py`
- Create: `tests/test_matching.py`
- Modify: `bokpilot/parsers.py`
- Modify: `bokpilot/repository.py`
- Modify: `bokpilot/server.py`
- Create: `scripts/run_demo.py`
- Modify: `bokpilot/resources/static/index.html`
- Modify: `bokpilot/resources/static/app.js`

**Interfaces:**

- Produces: `preview_import`, `commit_import`, `ImportPreview`, `ImportIssue`, `suggest_matches`, and explicit import/match API routes.
- Import routes: `POST /api/imports/preview`, `GET /api/imports/{batch_id}`, `POST /api/imports/{batch_id}/commit`, `POST /api/sources/{source_id}/attachment`.
- Match routes: `GET /api/sources/{source_id}/matches`, `POST /api/matches/{match_id}/decision`.
- A preview stores no reviewable source record until commit; a repeated commit with the same source hash is idempotent.

- [ ] **Step 1: Write failing import-preview tests**

Use a three-row CSV with one valid row, one invalid date, and one ambiguous amount. Assert that preview returns one candidate and two row-specific issues instead of aborting the entire file. Also assert:

```python
self.assertEqual(preview.source_filename, "seb-july.csv")
self.assertEqual(preview.candidates[0].source_row, 2)
self.assertEqual(len(preview.source_sha256), 64)
self.assertFalse(preview.committed)
```

Commit the same preview twice and assert that the second response reports zero new rows and the same imported IDs.

- [ ] **Step 2: Run focused tests and confirm current all-or-nothing import fails**

Run: `python3 -m unittest tests.test_imports -v`

Expected: FAIL because the current parser raises on the first malformed row and writes valid rows immediately.

- [ ] **Step 3: Implement immutable preview results**

Define:

```python
@dataclass(frozen=True)
class ImportIssue:
    source_row: int | None
    field: str
    code: str
    message: str


@dataclass(frozen=True)
class ImportPreview:
    batch_id: str
    kind: SourceKind
    source_filename: str
    media_type: str
    source_sha256: str
    decoded_bytes: int
    candidates: tuple[SourceRecord, ...]
    issues: tuple[ImportIssue, ...]
    committed: bool
```

`POST /api/imports/preview` accepts this JSON shape:

```json
{
  "kind": "bank_transaction",
  "filename": "seb-july.csv",
  "media_type": "text/csv; charset=utf-8",
  "content_base64": "RGF0dW07QmVza3Jpdm5pbmc7QmVsb3BwCg==",
  "locale": "sv-SE"
}
```

Support `bank_transaction`, `receipt`, `supplier_invoice`, and `customer_invoice`. Decode with `base64.b64decode(value, validate=True)`, reject decoded content over `10 * 1024 * 1024` bytes, compute SHA-256 over those original bytes, and preserve them unchanged. Allow declared text charsets `utf-8`, `utf-8-sig`, and `windows-1252`; reject unsupported or undecodable text with a typed issue. For CSV, detect delimiter/header aliases, parse each row independently, and retain the original row number. The browser converts `File.arrayBuffer()` to base64 without first decoding it as text.

- [ ] **Step 4: Add column mapping only when detection is incomplete**

Return normalized header candidates for `date`, `description`, `amount`, `debit`, `credit`, `currency`, and `counterparty`. The commit endpoint rejects a batch until required mappings are unambiguous. Persist the chosen mapping in `import_batches` so the import is reproducible.

- [ ] **Step 5: Store source evidence by hash without silent truncation**

For CSV and supported text documents, write the original bytes under `data/attachments/{sha256}` with mode `0600`; store original filename, media type, byte count, and hash in the database and set evidence status `available`. Verify the hash after writing. Manual entries use evidence status `manual_attested` and require a reviewer note. Preview bytes live in a private staging directory keyed by batch ID and are deleted only after commit or after an explicit 24-hour abandoned-preview cleanup. The UI may show an extracted excerpt, but the source record points to the complete local attachment.

`POST /api/sources/{source_id}/attachment` uses the same filename/media-type/base64 contract plus `expected_version`. It is accepted only when the source currently has no attachment, records a structured attachment event, sets evidence status `available`, increments source/workspace versions, and never overwrites an existing attachment.

- [ ] **Step 6: Implement deterministic import idempotency**

For file imports, set `import_key` to `f"sha256:{source_sha256}:{source_row if source_row is not None else -1}:{kind.value}"`. The unique database index is on that mandatory key, so records without a row number remain idempotent. `POST /api/imports/{batch_id}/commit` accepts `{"expected_workspace_revision":4}`, performs one transaction, returns `created_ids`, `existing_ids`, `issue_count`, and the new workspace revision, and never creates a second copy of an identical record. A stale revision returns `409`.

After commit, create unresolved duplicate candidates for different import keys with the same date, amount, currency, and normalized description. Do not collapse them automatically: recurring fees can be legitimate. Task 6 supplies the audited `not_duplicate` and `confirmed_duplicate` decisions.

- [ ] **Step 7: Write failing match scenarios**

Cover exact amount/date, a three-day date tolerance, partial payment, multiple equal candidates, already-confirmed matches, and different currencies. A candidate with different currency must never auto-score as a match.

- [ ] **Step 8: Implement explainable suggestions, never automatic reconciliation**

`suggest_matches(source_id)` may score same-currency records by amount, date distance, counterparty tokens, and reference tokens. Return component reasons with the score. A human must confirm or reject the match; confirmed matches create a structured event and cannot exceed the remaining unmatched amount.

`POST /api/matches/{match_id}/decision` accepts `{"decision":"confirmed","matched_minor":24900,"expected_version":3}` or `{"decision":"rejected","matched_minor":0,"expected_version":3}`. It returns the new match/source versions and workspace revision, and HTTP `409` on stale input. Confirmation never approves a posting draft by itself.

- [ ] **Step 9: Run checks and commit**

Run:

```bash
python3 -m unittest tests.test_imports tests.test_matching -v
python3 -m unittest -v
git diff --check
git add bokpilot/imports.py bokpilot/matching.py bokpilot/parsers.py bokpilot/repository.py bokpilot/server.py bokpilot/resources/static tests
git commit -m "feat: preview imports and suggest source matches"
```

---

### Task 6: Enforce Auditable Review and a Fail-Closed HTTP Boundary

**Files:**

- Create: `bokpilot/review.py`
- Create: `bokpilot/security.py`
- Create: `tests/test_review.py`
- Create: `tests/test_security.py`
- Modify: `bokpilot/repository.py`
- Modify: `bokpilot/server.py`
- Modify: `bokpilot/resources/static/app.js`
- Modify: `bokpilot/resources/static/index.html`
- Modify: `scripts/smoke_installed.py`
- Modify: `tests/test_server_api.py`
- Modify: `SECURITY.md`

**Interfaces:**

- Produces: `approval_issues`, `record_review`, `record_duplicate_decision`, immutable review revisions, item/workspace versions, session token validation, typed API errors, and safe reset semantics.
- Review requests include `expected_version`; stale requests return HTTP `409` and do not change the item. Successful reviews return the new item version and workspace revision.

- [ ] **Step 1: Write failing review-policy tests**

Assert that approval is rejected for unknown nature/VAT, unsupported currency, invalid account, inconsistent VAT, unbalanced lines, unacknowledged risk flags, an unresolved duplicate candidate, and a stale item version. Assert that a structured `not_duplicate` decision with a reviewer note clears only that candidate, while `confirmed_duplicate` makes the record non-exportable. Rejection remains allowed with a reviewer note because rejection does not make a posting exportable.

- [ ] **Step 2: Write failing HTTP security tests**

Cover:

- cross-origin `text/plain` POST to `/api/reset` returns `403` and leaves data intact;
- missing or incorrect `X-Bokpilot-Token` returns `403`;
- non-JSON mutation requests return `415`;
- a JSON body larger than `14 * 1024 * 1024` bytes returns `413` without reading or writing a workspace record, while decoded file content remains capped at 10 MiB;
- `Host: attacker.example:8765` is rejected before `/api/session` or any static/API route is served, even when the hostname resolves to loopback;
- unknown `/api/*` returns JSON `404`, not the SPA;
- internal exceptions return a stable error code without local paths or exception text;
- API/export responses include `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`;
- starting on a non-loopback address exits with an actionable error.

- [ ] **Step 3: Implement a startup session token and origin check**

Before routing any request, derive an allowlist from the bound loopback address and actual server port. For port `8765`, the only accepted values are `127.0.0.1:8765`, `localhost:8765`, and `[::1]:8765` when the server is bound for that address family. Ephemeral-port tests substitute the actual `server.server_address[1]`. Reject every other host with `421 Misdirected Request` and do not issue a session token. This is the DNS-rebinding boundary.

Generate `secrets.token_urlsafe(32)` when the server starts. Same-origin UI code fetches the token from `GET /api/session` and sends it in `X-Bokpilot-Token` on every mutation. If an `Origin` header is present, its scheme/host/port must equal the validated request origin; missing `Origin` still requires the token.

Update the installed-wheel smoke and API test helper to fetch `/api/session` first, include the returned token on mutation requests, and send that response's workspace revision when loading samples. Never enable an `Access-Control-Allow-Origin` response header.

- [ ] **Step 4: Add the exact HTTP policy**

Use these response headers:

```text
Content-Security-Policy: default-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'
Referrer-Policy: no-referrer
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
```

Add `Cache-Control: no-store` for `/api/*` and every export. Parse `Content-Length` before reading, reject negative/invalid lengths, cap JSON request bodies at `14 * 1024 * 1024` bytes, and require `application/json` for mutation routes. Import decoding separately enforces the 10 MiB decoded-file limit.

- [ ] **Step 5: Return structured errors**

Every API failure uses this shape:

```json
{
  "error": {
    "code": "approval_blocked",
    "message": "Resolve the highlighted review issues before approval.",
    "fields": {"vat": "VAT amount and treatment disagree."}
  }
}
```

Log only error code, route, and generated request ID to stderr. Do not log payloads, document text, bank rows, or local data paths.

- [ ] **Step 6: Preserve immutable review history**

On every decision, insert a review row containing decision ID, source ID, prior item version, reviewer note, risk acknowledgement, before-suggestion snapshot, selected values, posting snapshot, rule ID/version, timestamp, and action. Increment the item version atomically. Reopening creates another review row; it never edits the earlier one.

Add `POST /api/sources/{source_id}/duplicate-decision` with `{"duplicate_candidate_id":"dup-0002","decision":"not_duplicate","note":"Recurring monthly fee","expected_version":2}` or decision `confirmed_duplicate`. Store the decision as an immutable event and update the candidate status/version. `not_duplicate` clears that one gate; `confirmed_duplicate` changes source status to `duplicate` and excludes it from every export. A later reversal creates another event and requires the then-current version.

- [ ] **Step 7: Make sample loading and reset safe**

`POST /api/load-sample` requires a payload such as `{"expected_workspace_revision":0}` and returns `409 workspace_not_empty` when real items exist. `POST /api/reset` requires a payload such as `{"confirmation":"RESET","expected_revision":7}` and creates a verified `.bokpilot-backup` bundle containing the database, attachments, and export artifacts before clearing records. The UI sends the actual loaded revision, shows the backup path and checksum after success, and requires an explicit confirmation dialog.

- [ ] **Step 8: Run checks and commit**

Run:

```bash
python3 -m unittest tests.test_review tests.test_security tests.test_server_api -v
python3 -m unittest -v
node --check bokpilot/resources/static/app.js
git diff --check
git add bokpilot/review.py bokpilot/security.py bokpilot/repository.py bokpilot/server.py bokpilot/resources/static scripts/smoke_installed.py tests SECURITY.md
git commit -m "feat: make local review auditable and fail closed"
```

---

### Task 7: Produce Privacy-Safe Downloads and Validated SIE 4I

**Files:**

- Create: `bokpilot/sie.py`
- Create: `tests/fixtures/sie/approved-packet.se`
- Create: `tests/test_exports.py`
- Create: `tests/test_sie.py`
- Create: `docs/release-checklist.md`
- Modify: `bokpilot/exports.py`
- Modify: `bokpilot/server.py`
- Modify: `bokpilot/repository.py`
- Modify: `bokpilot/resources/static/app.js`
- Modify: `tests/test_store_exports.py`
- Modify: `docs/example-workflows.md`
- Modify: `docs/safety-and-privacy.md`

**Interfaces:**

- Produces: `create_json_batch`, `create_csv_batch`, `create_sie4i_batch`, `ExportBatch`, byte-safe download responses, and deterministic SHA-256 checksums.
- Create route: `POST /api/exports` accepts `{"format":"csv","review_ids":["review-1"],"expected_workspace_revision":12}`; formats are `json`, `csv`, and `sie4i`.
- Download route: `GET /api/exports/{batch_id}/download` reads an immutable content-addressed artifact and verifies its checksum before responding.
- SIE reference: [SIE 1-4 specification edition 4C](https://sie.se/wp-content/uploads/2026/02/SIE_filformat_ver_4C_2025-08-06.pdf); validation service: [SIE test service](https://sietest.sie.se/).

- [ ] **Step 1: Write failing privacy and injection tests**

Assert that default JSON omits `document_text`, attachment paths, and raw bytes. Assert that user text beginning with `=`, `+`, `-`, or `@` cannot become a spreadsheet formula in CSV. Assert that CR/LF, braces, quotes, and control characters in descriptions cannot inject a second SIE record.

- [ ] **Step 2: Write failing SIE conformance fixtures**

Require the output bytes to:

- decode as CP437 and fail UTF-8 decoding when the fixture contains Swedish account names;
- contain `#FLAGGA 0`, the line `f'#PROGRAM "Bokpilot" {bokpilot.__version__}'`, `#FORMAT PC8`, `#GEN`, `#SIETYP 4`, `#FNAMN`, declared `#KONTO` rows, and balanced `#VER`/`#TRANS` groups;
- use the configured company, fiscal year, currency, and voucher series rather than hardcoded demo values;
- reject unsupported currency, missing profile data, invalid account/date tokens, and unencodable characters with an export issue instead of lossy replacement.

- [ ] **Step 3: Implement share-safe JSON and CSV**

JSON schema version `2` includes export metadata, source IDs/hashes, normalized source fields, immutable review decision, posting lines, and audit IDs. CSV applies formula neutralization only to user-controlled text cells; numeric amount cells are emitted from integer minor units with exactly two decimal places.

- [ ] **Step 4: Implement SIE text sanitization and CP437 bytes**

Use a sanitizer equivalent to:

```python
def sie_text(value: str) -> str:
    cleaned = " ".join(value.replace("\r", " ").replace("\n", " ").split())
    if any(ord(character) < 32 for character in cleaned):
        raise ValueError("SIE text contains a control character.")
    return cleaned.replace('"', "'")
```

Build Unicode lines only after validating every token, join with `\r\n`, and encode once with `text.encode("cp437", errors="strict")`.

- [ ] **Step 5: Persist immutable export batches**

Write generated bytes once to `data/exports/{sha256}` with mode `0600`, fsync, and atomically rename from a same-directory temporary file. Record batch ID, format, schema/spec version, included review IDs, generated time, byte count, artifact SHA-256, relative artifact path, and safe filename. Re-download reads those stored bytes, verifies byte count/hash, and therefore remains identical after code or version changes. A changed review requires a new batch; export artifacts are deleted only by a separate explicit retention action outside v0.2.

- [ ] **Step 6: Return actual downloads**

Set format-specific `Content-Type` and a sanitized header such as `Content-Disposition: attachment; filename="bokpilot-export-20260711.csv"`. The UI creates a Blob, triggers a download, displays included item count and checksum, and keeps the text preview secondary.

- [ ] **Step 7: Prepare the synthetic SIE validation packet**

Generate the synthetic fixture, record its local parser result and checksum in `docs/release-checklist.md`, and keep the official-service gate open until Task 9 sets the final version. Never use a real user's packet for validation.

- [ ] **Step 8: Run checks and commit**

Run:

```bash
python3 -m unittest tests.test_exports tests.test_sie tests.test_server_api -v
python3 -m unittest -v
git diff --check
git add bokpilot/sie.py bokpilot/exports.py bokpilot/server.py bokpilot/repository.py bokpilot/resources/static/app.js tests docs
git commit -m "feat: add reproducible review packet downloads"
```

---

### Task 8: Turn the UI into a Clear, Accessible Review Workflow

**Files:**

- Modify: `bokpilot/resources/static/index.html`
- Modify: `bokpilot/resources/static/styles.css`
- Modify: `bokpilot/resources/static/app.js`
- Modify: `docs/assets/bokpilot-dashboard.png`
- Modify: `docs/assets/bokpilot-mobile.png`
- Modify: `docs/release-checklist.md`
- Create: `tests/test_static_ui.py`

**Interfaces:**

- Consumes: preview/import, paginated queue, review issues/history, match suggestions, and export batch APIs.
- Produces: onboarding, explicit row controls, source provenance, risk-first queue, keyboard review-next flow, safe destructive confirmations, and responsive desktop/mobile layouts.

- [ ] **Step 1: Write failing static accessibility tests**

Use `html.parser` to assert unique IDs, labels for form controls, real buttons/links for interactions, a skip link, one page-level `h1`, an error summary with `role="alert"`, status messaging with `role="status"`, and no `tabindex="0"` on table rows.

- [ ] **Step 2: Add a three-step first-run corridor**

Show `1. Company profile`, `2. Import and validate`, and `3. Review and export`. The profile requires company name, accounting method, fiscal-year start/end, currency `SEK`, and voucher series before SIE export; JSON/CSV review packets may remain available without organization number.

- [ ] **Step 3: Replace immediate import with preview UI**

Show detected columns, valid/invalid row counts, row-level issues, source hash, and a clear `Commit valid rows` button. Never commit merely because a file was selected.

- [ ] **Step 4: Make provenance and audit history visible**

The detail panel shows source filename, row, attachment-hash prefix when available, an explicit legacy-source-unavailable state otherwise, extracted fields, original suggestion, each review revision, posting lines, and all blocking/warning issues. Raw document text stays collapsed behind a privacy warning.

- [ ] **Step 5: Make queue review efficient**

Add search, status, risk, confidence, source-kind, and unresolved filters; sortable date/amount columns; explicit buttons labelled like `Review BP-0001`; previous/next controls; and stable focus on the next item after a decision. Disable controls while a request is pending and surface structured field errors next to their inputs.

- [ ] **Step 6: Improve responsive navigation and destructive flows**

On widths below `700px`, collapse the large sidebar into a compact top navigation, keep primary actions visible, render metrics in a two-column grid, and use card-style queue rows rather than forcing a wide table. Reset and sample actions require modal confirmation and describe backup behavior.

- [ ] **Step 7: Verify keyboard, mobile, and error states in the running app**

Run:

```bash
python3 scripts/run_demo.py --data-path /tmp/bokpilot-ui.sqlite3 --port 8765
```

`scripts/run_demo.py` injects the test-only approved catalog through `make_server("127.0.0.1", arguments.port, repository, catalog=approved_test_catalog(), demo_mode=True)` and displays a persistent `Synthetic accounting rules—do not use for real bookkeeping` banner. The normal `python3 -m bokpilot` path never loads this catalog.

Verify at `1440x900` and `390x844`: first run, mixed-validity import, keyboard-only review, blocked approval, stale-version conflict, synthetic confirmed approval, JSON/CSV/SIE download, reset cancellation, and offline restart. Capture the updated screenshots only after those paths pass.

- [ ] **Step 8: Run checks and commit**

Run:

```bash
python3 -m unittest tests.test_static_ui tests.test_server_api -v
node --check bokpilot/resources/static/app.js
python3 -m unittest -v
git diff --check
git add bokpilot/resources/static scripts/run_demo.py docs/assets docs/release-checklist.md tests/test_static_ui.py
git commit -m "feat: improve the local review experience"
```

---

### Task 9: Establish CI, Documentation, and the v0.2 Release Gate

**Files:**

- Modify: `.github/workflows/ci.yml`
- Create: `CHANGELOG.md`
- Create: `.github/ISSUE_TEMPLATE/bug_report.yml`
- Create: `.github/ISSUE_TEMPLATE/parser_fixture.yml`
- Create: `.github/pull_request_template.md`
- Create: `docs/backup-and-restore.md`
- Modify: `README.md`
- Modify: `CONTRIBUTING.md`
- Modify: `SECURITY.md`
- Modify: `.gitignore`
- Modify: `pyproject.toml`
- Modify: `bokpilot/accounts.py`
- Modify: `bokpilot/__init__.py`
- Modify: `docs/launch-checklist.md`
- Modify: `docs/release-checklist.md`

**Interfaces:**

- Produces: one required `CI` check, reproducible contributor commands, a centralized `0.2.0` version, a release evidence checklist, and privacy-safe issue intake.
- External repository settings remain approval-gated and occur only after code checks are stable.

- [ ] **Step 1: Add one local check command**

Document this exact pre-commit sequence in `CONTRIBUTING.md`:

```bash
python3 -m unittest -v
python3 -m compileall -q bokpilot tests
node --check bokpilot/resources/static/app.js
python3 scripts/smoke_installed.py --build-wheel
git diff --check
```

- [ ] **Step 2: Expand CI across supported Python versions**

Keep the remote workflow's current checkout/setup actions, expand the matrix to `3.10`, `3.11`, `3.12`, `3.13`, and `3.14`, and run the exact local check sequence. The wheel smoke job must install the built artifact into a clean environment and fail if any runtime asset is absent.

- [ ] **Step 3: Harden repository hygiene**

Ignore `.env` and `.env.*` while explicitly retaining `!.env.example`. Ignore `*.sqlite3`, SQLite journal/WAL files, attachment directories, backups, coverage output, wheel/build output, and local workspace artifacts. Confirm tracked samples remain synthetic.

- [ ] **Step 4: Centralize and set the release version**

Use `bokpilot.__version__ = "0.2.0"` as the single version source and configure setuptools dynamic version metadata from that attribute. Read the same value in workspace metadata, API responses, and SIE `#PROGRAM` output.

- [ ] **Step 5: Complete user and contributor documentation**

README quick start must cover clone, virtual environment, editable install, wheel install, data location, supported input formats, backup/restore, migration, troubleshooting, exact safety boundary, and how to uninstall without deleting user data. Clarify that `.env.example` documents process variables but is not auto-loaded.

- [ ] **Step 6: Make accounting and privacy release gates explicit**

The release checklist requires:

- all enabled rules marked `approved` in `docs/accounting-evidence.md` by a named qualified reviewer and dated review;
- the synthetic SIE fixture regenerated after setting version `0.2.0`, uploaded to the official SIE test service, and its specification edition, validation date, checksum, and result recorded;
- zero unresolved high-priority security/privacy regressions;
- migration and restore rehearsal from a v0.1 JSON fixture;
- wheel smoke on Python 3.10 and 3.14;
- desktop/mobile/keyboard corridor evidence;
- confirmation that default exports contain no raw documents or local paths.

The qualified-accountant review and official SIE upload are manual external gates. At execution time, stop and request the user's direction before sending the synthetic fixture to the test service or naming a reviewer. Record `blocked` when either gate has not actually happened; never infer, fabricate, or self-approve it.

After a real qualified review, update the matching entries in `bokpilot/accounts.py` and `docs/accounting-evidence.md` with the same reviewer name, date, source, and `approved` status. Production remains fail-closed if no entry is approved.

- [ ] **Step 7: Add private reporting and contribution templates**

Point `SECURITY.md` to GitHub private vulnerability reporting once enabled. Issue forms must warn users not to attach real receipts, invoices, bank rows, identity data, or tokens; the parser fixture form requires anonymized or synthetic data.

- [ ] **Step 8: Run the final local release-candidate gate**

Run:

```bash
python3 -m unittest -v
python3 -m compileall -q bokpilot tests
node --check bokpilot/resources/static/app.js
python3 scripts/smoke_installed.py --build-wheel
git diff --check
git fsck --full --no-reflogs
git archive HEAD >/dev/null
```

Expected: every command exits `0`; the working tree contains only the intended release commit if it has not yet been created.

- [ ] **Step 9: Commit the release candidate**

Run:

```bash
git add .github .gitignore CHANGELOG.md README.md CONTRIBUTING.md SECURITY.md pyproject.toml bokpilot/accounts.py bokpilot/__init__.py docs tests/fixtures/sie/approved-packet.se
git commit -m "chore: prepare Bokpilot 0.2.0"
```

Do not push, tag, create a release, enable branch protection, or change GitHub security settings without an explicit user request at execution time.

---

## Normative Cross-Task Contracts

These contracts remove discretion at the security, persistence, and accounting boundaries. A task implementer may split private helpers, but must not rename fields, weaken checks, or change state transitions without updating this plan and its tests first.

### SQLite schema contract

```sql
PRAGMA foreign_keys = ON;

CREATE TABLE workspace_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  revision INTEGER NOT NULL
);
INSERT INTO workspace_state(id, revision) VALUES (1, 0);

CREATE TABLE company_profile (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  name TEXT NOT NULL,
  accounting_method TEXT NOT NULL CHECK (accounting_method IN ('cash', 'accrual')),
  fiscal_year_start TEXT NOT NULL,
  fiscal_year_end TEXT NOT NULL,
  currency TEXT NOT NULL CHECK (length(currency) = 3),
  voucher_series TEXT NOT NULL,
  organization_number TEXT
);

CREATE TABLE source_attachments (
  sha256 TEXT PRIMARY KEY CHECK (length(sha256) = 64),
  relative_path TEXT NOT NULL UNIQUE,
  original_filename TEXT NOT NULL,
  media_type TEXT NOT NULL,
  byte_count INTEGER NOT NULL CHECK (byte_count >= 0),
  created_at TEXT NOT NULL
);

CREATE TABLE sources (
  id TEXT PRIMARY KEY,
  import_key TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('bank_transaction', 'receipt', 'supplier_invoice', 'customer_invoice', 'manual')),
  occurred_on TEXT NOT NULL,
  amount_minor INTEGER NOT NULL,
  currency TEXT NOT NULL CHECK (length(currency) = 3),
  description TEXT NOT NULL,
  counterparty TEXT NOT NULL,
  source_filename TEXT NOT NULL,
  source_row INTEGER,
  attachment_sha256 TEXT REFERENCES source_attachments(sha256),
  evidence_status TEXT NOT NULL CHECK (evidence_status IN ('available', 'manual_attested', 'legacy_unavailable')),
  extracted_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('needs_review', 'approved', 'rejected', 'duplicate')),
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);

CREATE TABLE suggestions (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(id),
  rule_id TEXT,
  rule_version INTEGER,
  snapshot_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE reviews (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(id),
  prior_version INTEGER NOT NULL,
  action TEXT NOT NULL CHECK (action IN ('approved', 'rejected', 'reopened')),
  decision_json TEXT NOT NULL,
  posting_json TEXT,
  reviewer_note TEXT NOT NULL,
  risk_acknowledged INTEGER NOT NULL CHECK (risk_acknowledged IN (0, 1)),
  rule_id TEXT,
  rule_version INTEGER,
  created_at TEXT NOT NULL
);

CREATE TABLE posting_drafts (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(id),
  review_id TEXT REFERENCES reviews(id),
  lines_json TEXT NOT NULL,
  issues_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE import_batches (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  source_filename TEXT NOT NULL,
  media_type TEXT NOT NULL,
  source_sha256 TEXT NOT NULL CHECK (length(source_sha256) = 64),
  byte_count INTEGER NOT NULL,
  locale TEXT NOT NULL,
  mapping_json TEXT NOT NULL,
  issues_json TEXT NOT NULL,
  staging_relative_path TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('previewed', 'committed', 'abandoned')),
  created_at TEXT NOT NULL,
  committed_at TEXT
);

CREATE TABLE duplicate_candidates (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(id),
  candidate_id TEXT NOT NULL REFERENCES sources(id),
  status TEXT NOT NULL CHECK (status IN ('suggested', 'not_duplicate', 'confirmed_duplicate')),
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  UNIQUE(source_id, candidate_id)
);

CREATE TABLE duplicate_decisions (
  id TEXT PRIMARY KEY,
  duplicate_candidate_id TEXT NOT NULL REFERENCES duplicate_candidates(id),
  decision TEXT NOT NULL CHECK (decision IN ('not_duplicate', 'confirmed_duplicate')),
  reviewer_note TEXT NOT NULL,
  prior_version INTEGER NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE matches (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(id),
  candidate_id TEXT NOT NULL REFERENCES sources(id),
  suggested_minor INTEGER NOT NULL CHECK (suggested_minor >= 0),
  score REAL NOT NULL CHECK (score >= 0 AND score <= 1),
  reasons_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('suggested', 'confirmed', 'rejected')),
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);

CREATE TABLE export_batches (
  id TEXT PRIMARY KEY,
  format TEXT NOT NULL CHECK (format IN ('json', 'csv', 'sie4i')),
  schema_version TEXT NOT NULL,
  spec_version TEXT,
  review_ids_json TEXT NOT NULL,
  artifact_sha256 TEXT NOT NULL CHECK (length(artifact_sha256) = 64),
  artifact_relative_path TEXT NOT NULL UNIQUE,
  byte_count INTEGER NOT NULL CHECK (byte_count >= 0),
  filename TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX review_queue_idx ON sources(status, occurred_on, id);
CREATE UNIQUE INDEX source_import_key_uq ON sources(import_key);
CREATE INDEX matches_source_idx ON matches(source_id, status);
```

`PRAGMA user_version` is set to `2` only after all statements commit. All JSON columns contain canonical JSON with sorted keys and compact separators.

### Mutation transaction contract

```python
from contextlib import contextmanager
from dataclasses import dataclass
import sqlite3


class ConflictError(RuntimeError):
    pass


@dataclass
class MutationSession:
    connection: sqlite3.Connection
    revision: int


@contextmanager
def mutation(self, expected_revision: int | None = None):
    connection = self.connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        current = connection.execute(
            "SELECT revision FROM workspace_state WHERE id = 1"
        ).fetchone()[0]
        if expected_revision is not None and current != expected_revision:
            raise ConflictError("workspace_revision_conflict")
        session = MutationSession(connection=connection, revision=current)
        yield session
        connection.execute(
            "UPDATE workspace_state SET revision = revision + 1 WHERE id = 1"
        )
        session.revision = connection.execute(
            "SELECT revision FROM workspace_state WHERE id = 1"
        ).fetchone()[0]
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()
```

Callers execute SQL through `session.connection` and return `session.revision` after the context exits; no shared mutable revision field exists and no method opens a nested mutation transaction.

### Import and match contract

- Import preview validates Host/token/body policy, base64, decoded size, media type, charset, mapping, and each row in that order.
- Commit re-hashes staged bytes, checks `expected_workspace_revision`, inserts or selects by `import_key`, creates unresolved duplicate candidates, moves the staged attachment by hash, and commits once.
- Matching rejects different currencies. Score is `0.50` for exact remaining amount or `0.30` for a valid partial amount, plus `0.20` for date distance 0-1 days or `0.10` for 2-3 days, plus `0.15` for at least 50% normalized-counterparty token overlap, plus `0.15` for an exact non-empty reference token. Only scores `>= 0.60` are returned. Ties remain separate suggestions.
- Confirmation checks both records' remaining unmatched minor units and item version inside one transaction. It never approves either record.

### Approval issue contract

`approval_issues` returns stable codes in this order: `unsupported_currency`, `unknown_nature`, `unknown_vat`, `invalid_account`, `vat_exceeds_gross`, `vat_treatment_mismatch`, `journal_unbalanced`, `duplicate_unresolved`, `risk_acknowledgement_required`, `reviewer_note_required`, `source_evidence_unavailable`. Approval is allowed only when the tuple is empty. `source_evidence_unavailable` is emitted only for `EvidenceStatus.LEGACY_UNAVAILABLE` and may be resolved only by attaching a verified source file or by rejecting the record; a note alone does not clear it. `MANUAL_ATTESTED` is allowed only with a non-empty reviewer note.

### API route contract

| Method | Route | Success | Concurrency input |
| --- | --- | --- | --- |
| GET | `/api/session` | token and workspace revision | none |
| GET | `/api/workspace` | paginated summary and revision | none |
| POST | `/api/imports/preview` | `ImportPreview` | token |
| POST | `/api/imports/{batch_id}/commit` | IDs, issues, new revision | expected workspace revision |
| POST | `/api/sources/{source_id}/attachment` | attachment hash, source version, revision | expected source version |
| GET | `/api/sources/{source_id}/matches` | scored suggestions | none |
| POST | `/api/matches/{match_id}/decision` | match/source versions and revision | expected match version |
| POST | `/api/sources/{source_id}/duplicate-decision` | source version and revision | expected source version |
| POST | `/api/items/{source_id}/review` | source version and revision | expected source version |
| POST | `/api/load-sample` | sample workspace and revision | expected workspace revision |
| POST | `/api/reset` | backup path/checksum and revision | expected workspace revision plus confirmation |
| POST | `/api/exports` | batch metadata and revision | expected workspace revision |
| GET | `/api/exports/{batch_id}/download` | stored artifact bytes | none |

All mutation responses use HTTP `201` for newly created resources, `200` for decisions, `409` for version conflicts, `422` for domain validation, and the Task 6 error schema.

`GET /api/workspace` accepts `status`, `source_kind`, `risk`, `query`, `cursor`, and `limit`; `limit` defaults to `50` and is constrained to `1..100`. The cursor is URL-safe base64 of canonical JSON `{"occurred_on":"2026-07-11","id":"BP-0001"}` and queries use the tuple strictly after that record.

---

## Deferred Until After v0.2

- OCR/PDF layout extraction and any AI provider.
- Fortnox, Visma, Bokio, ERPNext, or Frappe write adapters.
- Multi-user hosting, authentication, encrypted cloud sync, and mobile apps.
- Automated tax filing, live voucher posting, payments, or account mutation.
- Full BAS catalog redistribution. A user-supplied import path can be designed after licensing and format review.
- Swedish UI translation; first finish the stable English information architecture and externalize copy keys.

## Definition of Done

Bokpilot v0.2 is complete only when a fresh clone is Git-healthy, a clean wheel install can run the full UI, source data remains exact and private, imports are previewed and idempotent, ambiguous accounting facts block approval, review history is immutable, concurrent operations cannot corrupt data, exports are reproducible downloads, the synthetic SIE 4I packet passes the official tester, and all local/CI/release gates above are green.

## Self-Review Checklist

- [ ] Every verified defect is addressed by a task and an acceptance check.
- [ ] The repository recovery happens before any implementation commit.
- [ ] Domain names and signatures are consistent across tasks.
- [ ] No code task depends on a live integration or paid dataset.
- [ ] Destructive and external actions remain explicitly approval-gated.
- [ ] The plan contains no unfinished placeholder instructions.

## Execution Handoff

Plan execution should use one of these routes after Task 0 creates the healthy checkout:

1. **Subagent-driven (recommended):** dispatch a fresh implementation agent per task, then run specification and quality review gates before moving to the next task.
2. **Inline execution:** run the tasks in this order in the recovered checkout with a verification checkpoint after every commit.
