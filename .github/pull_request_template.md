## Summary

Describe the scoped change and its safety impact.

## Verification

- [ ] `python3 -m unittest -v`
- [ ] `python3 -m compileall -q bokpilot tests`
- [ ] `node --check bokpilot/resources/static/app.js`
- [ ] `python3 scripts/smoke_installed.py --build-wheel`
- [ ] `git diff --check`

## Privacy and accounting

- [ ] Tests and fixtures are synthetic; no real financial, personal, credential, or local-path data is included.
- [ ] Accounting behavior remains a suggestion unless evidence and qualified review are recorded.
- [ ] User-visible behavior and safety documentation were updated where needed.
