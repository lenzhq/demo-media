# TODOs — deferred scope (decisions recorded, not forgotten)

From the 2026-07-23 CEO review of `PROJECT_BRIEF.md` (mode: SELECTIVE EXPANSION;
accepted: E1 editorial floor, E4 PR preview channels):

- ~~E2 — analytics~~ **DONE**: GA4 wired (build-time `GA_MEASUREMENT_ID`
  repo variable, set 2026-07-23 to the live property; non-hardcoded; previews
  and local builds don't track).
- **E3 — `/build-this/` developer page.** On-site walkthrough of how the site
  is built on the Lenz Python SDK (the README's content, surfaced where
  visitors are). The README covers this for v1.
- **E5 — Date archives / weekly digest email.** RSS covers freshness for v1.
- **Launch checklist (Pavel/Vicky, outside this repo):** link from
  lenz.io/developers; `@isthisbs` bot bio + reply links; Show HN post; domain
  DNS → Firebase (isthisbs.org).
- **X-bot link switch (Lenz repo, one-liner):** point the @isthisbs reply URL
  at `https://isthisbs.org/c/<verification_id>` (was lenz.io/c/). The /c/
  short-link system (static stubs + claimlive function fallback) serves the
  claim with a full OG card from second zero; the daily build absorbs it.
  Keep the bare-URL/no-UTM attribution decision.
- **Firebase Blaze plan required** before the first functions deploy (Cloud
  Functions gen2 needs billing enabled; volume ≈ pennies). provision-gcp.sh
  enables the APIs + SA roles already.
- **Lenz-side API extension (Lenz repo, separate PR):** make
  `GET /verifications/{id}/related` keyless public-read (list + detail already
  are; verified 2026-07-23). Until then the site uses entity-overlap fallback
  for MORE CHECKS. Second candidate: `modified_since` incremental catalog feed.
- **Future interactivity (votes/comments/challenges):** Firestore + anonymous
  auth + lazy JS islands; nightly build bakes aggregates back into static HTML.
  See PROJECT_BRIEF.md → "Future: interactivity layer".
