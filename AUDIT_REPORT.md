# End-to-end audit — FreeGate v7

## Fixed blockers
- Replacement quota was accidentally reset by creating a new batch for every replacement. Fixed: replacement stays inside the original package and consumes that package's quota.
- Replacement quota could be consumed before a healthy replacement existed. Fixed: health check succeeds first, then quota is consumed.
- Initial package refill created extra batches. Fixed: one package is created and all candidates belong to that package.
- Turso compatibility cursor lacked `lastrowid`. Fixed.
- Two admin handlers shared `a_sources`, making one screen unreachable. Fixed with `a_sources` for monitoring and `a_collector_sources` for collector list.
- User service UI exposed source names in one helper. Fixed: user-facing service buttons no longer include source names.
- Admin numeric commands could crash when argument was missing. Fixed with argument validation.
- `/addchannel` could crash when no argument was provided. Fixed.

## Behavioral checks
- One successful referral milestone creates one package.
- Package has up to five healthy configs; incomplete packages are not delivered.
- Each package owns its own replacement quota.
- A failed config is marked replaced only after a replacement is found and quota is available.
- A replacement is inserted into the original package, not a new package.
- User-facing messages do not reveal collector source names.

## Remaining architectural limitation
The current health engine still uses TCP reachability as its safe baseline. Merely opening a TCP connection does not prove a VPN tunnel works end-to-end. Protocol-specific runtime adapters should be treated as a separate, sandboxed capability and must only use locally installed trusted binaries/config templates.
