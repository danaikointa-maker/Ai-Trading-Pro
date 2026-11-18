# Broker account management

Open Brokers in the development dashboard at http://127.0.0.1:18000. Its API
uses the SSH tunnel at port 18080 to VM100's loopback port 8000.

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
