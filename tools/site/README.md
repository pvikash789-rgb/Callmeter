# Site build

The public pages in `docs/` are built from these templates.

- `journal-head.html` + `journal-body.html` -> `docs/index.html` (build journal)
- `log-head.html` + `log-body.html` -> `docs/decisions.html` (decision log)

To rebuild after editing a template:

```bash
python3 tools/site/build.py docs
```

New journal entries go at the top of the `<div class="journal">` block in `journal-body.html`.
New decisions go at the end of the ledger in `log-body.html`, numbered in order after the last one.
The trademark attribution footer is added by `build.py` to every page.
