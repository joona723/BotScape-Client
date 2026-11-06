# Local rs-sdk compatibility

This package implements the synchronous API used by the copied LostCity scripts,
using `sdk/botscape.py` and Bot Scape's HTTP gateway. It uses only Python's standard
library. It does not connect to an rs-sdk bridge or import an installed `rs` package.

Run from `bots/simba`, for example:

```powershell
python -u Mining.py codextest --main codextest --bronze --drop --minutes 1
```

`bots/simba/rs.py` imports this package and removes the manager's character and
`--main` prefix, preserving script-specific arguments. Child processes inherit
`RS_BOT` and `BOT_MAIN`. Passwords come from `bots/<main>/bot.env`; clones use their
main's password. An explicit `rs.connect_sync(name)` logs in that name. Closing a
controller does not log out the character; the manager owns that session.

`RSObject` supports both dictionary and attribute access. `Result` always exposes
`success`, `message`, `reason`, and `data`. High-level actions wait for snapshot
evidence; `send_*` methods acknowledge dispatch only. Dialog choices are zero-based
in the compatibility API and become one-based gateway choices. Interface IDs from
LostCity are refused because revision 233 uses different components; explicit
gateway component names remain usable.

The gateway sees only 15 tiles. Long walks use 12-tile intermediate clicks and
nearby doors, and stop if they cannot progress. This cannot replace a global
collision map or find routes around large obstacles. Radius scans return only
visible entities. No hidden state or administrative commands are used to make
ordinary script actions succeed.

Animation IDs, NPC engagement, exact combat targets, death counters, combat-style
data, quest progress, and shop stock are unavailable. Unknown values remain `None`;
player combat engagement is an estimate based on a target attacked by this
controller and the gateway's interaction flag. Shared idle detection instead uses
`interacting`, `moving`, `hasRoute`, and `delayed`. Snapshot `capabilities` records
important omissions. See `codex/PORT_REPORT.md` for the actual running-server
results and the distinction between absent content and unverified handlers.

Known unavailable script features stop with exit code 3 and a message. Methods
for unavailable features return a failed Result with reason `unsupported`.
`FeatureUnavailable` is a permanent feature failure rather than a connection
error, so it does not enter the source scripts' reconnection loops. Smithing
product selection, shop operations, spell targeting, equipment removal, banknote
selection, and global path queries need server/gateway support; they are never
emulated through admin commands.

Checks:

```powershell
python -m unittest codex.test_rs_compat -v
python -u codex/test_port_live.py
python -u codex/probe_port_live.py
```

The live tools control only `codextest`, enforce per-script time limits, preserve
its existing password, save evidence in `codex/port-tests`, and log it out in a
`finally` block. Do not run the two live tools concurrently.
