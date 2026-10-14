# Security

BacktestWitness executes the Python callback you supply. Treat it as ordinary local Python execution, and audit simulation entry points before using them. Generated reports are offline; they have no telemetry or built-in broker connection.

Importing a strategy or executing a generated pytest can run arbitrary Python. These operations are not sandboxed: use only trusted simulation code, keep live trading credentials out of its environment, and inspect externally supplied callback references before replay. The bundled public-case loader verifies pinned source hashes and selects simulation code; upstream API-fetching entry points are not executed.

HTML, JSON reports and replay fixtures retain complete simulation inputs and configuration. HTML embeds its JSON even when a section is collapsed. Treat these exports as private until reviewed. Recognized credential/contact/account fields, credential formats and home-directory paths are rejected before execution or export, without silently modifying hashes. Ordinary callback exception messages are omitted; `ExecutionUnavailable` is an explicit opt-in for a safe limitation message. These checks cannot identify every secret, personal identifier or proprietary strategy. Use synthetic or deliberately sanitized data for shared examples; hashes do not encrypt data.

The preview binds only to `127.0.0.1` and accepts its exact host/port and same origin. It serves known report artifacts only, rejects symlinks and directory listings, and disables external resources through a content security policy. Secure filesystem traversal is supported on macOS/Linux; other platforms fail closed. Opening generated HTML directly does not provide the HTTP preview's security headers. Do not expose the preview through a public tunnel or use it to host arbitrary downloaded HTML.

Source distributions strip local filesystem ownership and timestamps. Internal session notes, generated private artifacts, credential files and stale builds are excluded from publication. A public GitHub account or organization and its hosting activity are inherently visible; choose that identity before publishing. Third-party author names and license notices are retained as required attribution.

Report injection or path traversal issues with a minimal synthetic reproducer. Do not include secrets in public issue reports. Once this project is published, use the hosting platform's private vulnerability reporting feature if enabled; no reporting address is established for this local unreleased checkout.

Fixture hashes detect changes to content, not trustworthiness of code or origin. Future dependencies and financial losses are research/debugging concerns rather than security guarantees.
