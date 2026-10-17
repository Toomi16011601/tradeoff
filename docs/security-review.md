# Privacy and security review — 2026-10-14

Scope: publication files and Git history, current package archives and their headers, screenshot pixels/metadata, owned runtime, report export/rendering, local preview, bundled strategy loading, CI and declared dependency versions. Private trading projects were outside scope.

## Refresh — 17 October 2026

The final release audit rechecked all current publication candidates, both reachable commits, fresh source/wheel packages, archive headers, screenshots and bundled notices. It reproduced and fixed a direct Python export gap: tuples serialize as JSON arrays, so recognized sensitive fields now receive the same recursive checks inside tuples as lists. Cycle/depth limits remain enforced before either report writer creates files. Repair replay also now preserves the saved runner settings and starting capital; changing the simulation environment can no longer dilute a percentage-based failure into a passing repair.

Fresh [OSV](https://osv.dev/) API checks returned no matches for 28 public package-version pairs covering the clean lab resolution, pinned optional cases, and relevant build/development versions. Only public package names/versions were submitted. This is a dated advisory result, not a security certificate or complete transitive/native-library audit. The pinned [checkout commit](https://github.com/actions/checkout/commit/11d5960a326750d5838078e36cf38b85af677262) and [setup-python commit](https://github.com/actions/setup-python/commit/a26af69be951a213d495a4c3e4e4022e16d87065) resolve in their official upstream repositories.

Local ignored virtual environments, bytecode and build metadata can contain a local home path. They are excluded from the publication candidates and both archives; do not publish a raw workspace directory or force-add ignored files. Source and archive scans cannot establish globally leak-free status.

## Findings resolved

- Removed account-specific launch metadata and internal session records. Prepared a neutral publication history; original local history and stale archives are retained in a private backup outside the repository.
- Source builds strip local user/group names, numeric ownership and filesystem timestamps from tar/gzip metadata. The normal PEP 517 build path enforces this; extracted sdists still build wheels.
- Recognized credentials, contact/account fields and home-directory paths are rejected before execution/export. Checks also cover malformed observations, fixture references and gallery labels. Raw ordinary callback exception messages and their replay exception chains are omitted. Replay inputs and hashes are never silently redacted.
- Restricted preview to loopback, exact host/port and same origin. Every filesystem component opens without following symlinks; only known regular report artifacts are served. Directory listings, hidden paths and external resources are refused. CSP hashes authorize the packaged CSS/JavaScript.
- CI actions are pinned to public upstream commit refs, token access is read-only, and checkout credentials are not persisted. Development/build floors are pytest 9.0.3 and setuptools 83.0.0, retaining Python 3.10 support.

No actual API credentials were found in publication inputs. Supported built-in workflows have no telemetry, outbound HTTP/API requests or live brokerage integration. Pinned public source includes upstream data-fetching code for attribution; its hash-verified simulation loader omits those imports and entry points. Third-party names and license notices remain intact.

## Dependency evidence and limits

OSV checks returned no advisory matches for the 17 installed optional runtime packages: Backtesting 0.6.6, Backtrader 1.9.78.123, pandas 2.2.3, NumPy 2.3.5, Bokeh 3.10.0, Jinja2 3.1.6, narwhals 2.27.1, packaging 26.3, Pillow 12.3.0, PyYAML 6.0.3, Tornado 6.5.10, xyzservices 2026.9.1, MarkupSafe 3.0.4, python-dateutil 2.9.0.post0, pytz 2026.4, tzdata 2026.4 and six 1.17.0. Core has no third-party runtime dependencies. Queries sent only public package names/versions, with no source, user data or configuration.

Old allowed developer-tool versions had known advisories, including [pytest's fixed release](https://github.com/pytest-dev/pytest/releases/tag/9.0.3) and [setuptools's archive-exclusion fix](https://github.com/pypa/setuptools/commit/dd9f436a36486b4cb8a4c70a2321548b0be09b8f). The local installer was upgraded to pip 26.2.1, addressing its old installer findings and [Requests credential-selection issue](https://github.com/psf/requests/security/advisories/GHSA-9hjg-9r4m-mvj7). See [pip's release notes](https://pip.pypa.io/en/stable/news/#v26-2).

This is a version snapshot, not a dependency lock or proof against unknown vulnerabilities. Different platforms/resolutions, CPython/native-library CVEs and GitHub Actions' nested dependencies were not separately certified. The latest inspected pip still bundles urllib3 2.7.0 with two conditional advisories involving malicious downloads or a special HTTPS proxy TLS configuration; pip is installation tooling, not a BacktestWitness runtime import. Use trusted package sources and revisit advisories before release.

Imported callbacks and generated tests execute trusted local Python without a sandbox. Reports contain full inputs/configuration even inside HTML; recognized-pattern checks cannot identify every personal name, proprietary strategy or unknown secret format. Review artifacts before sharing. A public hosting account/organization is inherently visible. [Security policy](../SECURITY.md) defines these boundaries.
