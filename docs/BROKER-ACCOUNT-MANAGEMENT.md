# Broker account management

Open Brokers in the development dashboard at http://127.0.0.1:18000. Its API
uses the SSH tunnel at port 18080 to VM100's loopback port 8000.

MT5 terminal paths are detected from the running Windows terminal through the
bridge; users do not enter a path. The optional `MT5_TERMINAL_PATH` override is
for the Windows publisher only. A path in `.env` alone cannot attach to MT5 on
VM100 because the MT5 session runs on the Windows PC. The packaged bridge
terminal executable can be selected automatically when that exact terminal is
already running; the app never starts a saved-account terminal or logs in to it.
The official Python integration can also discover an installed terminal when
no path is supplied, but automatic Windows process matching is used here to
avoid selecting a different account when multiple terminals are installed.

Each saved account has compact edit and delete icons with labels/tooltips.
Owners and tenant administrators can manage unassigned records while execution
is disabled. Assigned accounts must first be returned to the owner using the
existing tenant administrator action. Team managers and viewers cannot change
the saved account identity or delete another owner's record.

Edit opens a form directly below the selected row. Blank replacement login and
password fields retain existing credentials; passwords are never returned by
the API. Cancel clears the draft without a request. Connection changes reset
Demo validation; changing only the display label retains validation. Live
execution remains disabled. A concurrent edit, assignment, or validation rejects
stale changes and requires refreshing the page. A validation already in progress
cannot overwrite the state of a changed or deleted record.
Validation checks the fresh Demo account identity and requested symbol quote on
the Windows bridge; it never sends an MT5 order.

Delete requires an explicit confirmation naming the saved account. It removes
the account record and its encrypted credentials without contacting MT5 or
removing trade evidence. It never closes the broker account or open positions.

Read-only terminal links offer rename and unlink separately. Unlink requires
confirmation and removes this user's access to private chart positions; it does
not stop the shared market publisher or change the terminal account. Linking
again requires a new one-use code. Configuration profiles shown below managed
accounts remain registry configuration rather than user-created account records.

Lifecycle API: PUT and DELETE `/api/broker-accounts/{id}` require the current
`expected_updated_at`. PUT `/api/market/terminal-links/{id}` accepts `label` and
`expected_label`; DELETE removes the authenticated owner's terminal link.
