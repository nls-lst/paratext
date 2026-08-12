# Publishing to PyPI

paratext is published as **`paratext-cli`**. The import package and the console
script are both `paratext` — only the distribution name carries the suffix,
because the plain `paratext` name on PyPI belongs to an unrelated project.

Releases go out through `.github/workflows/publish.yml` using **Trusted
Publishing**: GitHub Actions authenticates to PyPI over OIDC, so no API token is
stored in the repo, in an environment, or on anyone's laptop.

## One-time setup

PyPI needs to be told which workflow is allowed to publish. Because
`paratext-cli` does not exist there yet, this is registered as a **pending
publisher** — the first successful run creates the project.

1. Sign in to `pypi.org` (an account with 2FA enabled is required).
2. Go to **Your account → Publishing → Add a new pending publisher**.
3. Enter exactly:

   | Field | Value |
   |---|---|
   | PyPI Project Name | `paratext-cli` |
   | Owner | `nls-lst` |
   | Repository name | `paratext` |
   | Workflow name | `publish.yml` |
   | Environment name | `pypi` |

The environment name matters: the workflow declares `environment: pypi`, and
PyPI checks it. Add the `pypi` environment under **Settings → Environments** in
the GitHub repo if you want a required-reviewer gate on releases too — the
workflow needs no change for that.

Once the first release has published, the pending publisher becomes an ordinary
publisher attached to the project.

## Cutting a release

1. Bump `version` in `pyproject.toml` **and** `__version__` in
   `src/paratext/__init__.py`. A test asserts they agree, so a mismatch fails CI
   rather than shipping a wrong `paratext -v`.
2. Commit, push, and let CI go green.
3. Create a GitHub Release tagged `v<version>` (e.g. `v0.1.0`).

Publishing the release triggers the workflow, which:

- checks the tag matches `pyproject.toml` (a release tagged `v0.2.0` against a
  `0.1.0` package fails before anything is uploaded);
- runs ruff and pytest — the release may be cut from any commit, so CI having
  passed elsewhere is not the same as passing here;
- builds the sdist and wheel, and runs `twine check` on the metadata;
- uploads via `uv publish --trusted-publishing always`.

`always` is deliberate: if the publisher is misconfigured the job fails loudly
instead of quietly falling back to looking for a token that does not exist.

## Rehearsing

`workflow_dispatch` runs everything except the upload (`dry-run` defaults to
true), which is the cheapest way to check a release would build and pass.

For a real end-to-end rehearsal, TestPyPI is a separate site with its own
account and its own pending publisher:

```bash
uv publish --publish-url https://test.pypi.org/legacy/
```

## Things that cannot be undone

- **A version number is permanent.** Deleting a release from PyPI does not free
  the number — the fix for a bad `0.1.0` is `0.1.1`, never a re-upload.
- **The name is claimed on first upload.** Until then, `paratext-cli` is
  unreserved and someone else could take it.
