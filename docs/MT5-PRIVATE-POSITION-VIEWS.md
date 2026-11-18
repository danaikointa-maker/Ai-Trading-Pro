# Private MT5 position overlays

The market publisher can opt into reading open MT5 positions with
`--include-positions`. It never sends orders or changes SL/TP. This publisher
currently requires the already connected, explicitly selected Demo terminal.

Use `--link-code-file` with a file inside the existing protected
`%LOCALAPPDATA%\No7AITrading` directory. After a successful snapshot the publisher
writes a one-use code there. It expires after ten minutes. Do not publish the
file, code, or bridge token. Restart the publisher to issue a replacement code.

In the dashboard on port **18000**, open Brokers and paste the code into the
read-only terminal linking form. Then open the chart and select the linked
terminal account. POS displays actual position entry prices; SL/TP displays
only nonzero stop loss and take profit prices supplied by MT5. A position with
no SL/TP does not produce invented lines. Port **18080** forwards requests to
VM100's loopback API on port **8000**.

Links belong to the authenticated user's tenant and email. Shared market charts
never expose private positions. Changing the MT5 login/server or rotating the
bridge token invalidates the binding. Unlinking removes only dashboard access;
it does not close positions or alter MT5. Missing, failed, stale, or disconnected
position snapshots clear the overlays instead of reporting a confirmed empty
account. Private snapshots cannot be activated as a global execution broker.

Verification uses fixture positions, owner isolation, one-use and expiry tests,
publisher account-switch checks, and frontend chart mocks. It never opens real
positions to exercise the overlays.
