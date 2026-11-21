# Backup, restore, and migration

Bokpilot keeps its SQLite database, evidence attachments, and immutable export
artifacts in the local data directory. Backups are private, checksum-verified
ZIP_STORED bundles; they are not encrypted.

## Create a backup

```bash
python3 -m bokpilot backup \
  --data-path ./data/bokpilot.sqlite3 \
  --to ./backups/bokpilot-20260712.bokpilot-backup
```

Record the SHA-256 printed by the command separately from the bundle.

## Restore into a new directory

```bash
python3 -m bokpilot restore \
  --from ./backups/bokpilot-20260712.bokpilot-backup \
  --to ./data/restored-bokpilot \
  --sha256 SHA256_PRINTED_BY_BACKUP
```

Restore refuses a wrong checksum, unsafe archive paths, corrupt members, and an
existing non-empty destination. It runs SQLite integrity checks before the
verified database and artifacts are installed atomically.

## Migrate a v0.1 JSON workspace

```bash
python3 -m bokpilot migrate \
  --from-json ./data/workspace.json \
  --to-sqlite ./data/bokpilot.sqlite3
```

Migration never edits or deletes the source JSON, creates a verified source
backup, records the source hash, and is idempotent for the same input. Legacy
records are explicitly marked as lacking original evidence bytes; Bokpilot does
not invent attachment hashes.

## Reset behavior

The UI requires the exact `RESET` confirmation and the current workspace
revision. It creates and reports a verified backup before clearing database
records. Keep backup bundles outside repositories and protect them like the
original financial documents.
