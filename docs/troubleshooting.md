# When something looks wrong

- **A run finished but preprocessing didn't happen.** `run` prints a `!` notice
  for anything that degraded rather than failed — most often a card crop falling
  back to a content-aware crop because no detector was available.
- **An edit to `schema.py` or `prompt.md` had no effect.** `paratext inspect`
  reports the *installed* project. If it disagrees with your editor, reinstall
  (`uv sync`). An editable install avoids this entirely.
- **A field renamed in one place but not another.** `paratext inspect` runs the
  same audit as `audit_project`. Call it from your tests too.

