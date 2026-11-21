# Phase 10 boundary and demo

Run `docker compose up --build`, then check `/health`. Create a plan, confirm
`AWAITING_APPROVAL`, approve it, and call `/book` with an idempotency key.
Repeat that key to demonstrate no duplicate intent; edit the plan to invalidate
the old approval.

All transport, hotel and booking providers remain **MOCK**. Do not publish the
API: this MVP has no user identity/ownership enforcement. The Hue source
licence is unclear; confirm data/image rights before public or commercial use.
