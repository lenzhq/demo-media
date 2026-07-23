# TODOs — deferred scope (decisions recorded, not forgotten)

From the 2026-07-23 CEO review of `PROJECT_BRIEF.md` (mode: SELECTIVE EXPANSION;
accepted: E1 editorial floor, E4 PR preview channels):

- ~~E2 — analytics~~ **RESOLVED 2026-07-23: GA4 added** (build-time
  `GA_MEASUREMENT_ID` variable, non-hardcoded; previews don't track). Remaining
  launch step: create the GA4 property and set the repo variable.
- **E3 — `/build-this/` developer page.** On-site walkthrough of how the site
  is built on the Lenz Python SDK (the README's content, surfaced where
  visitors are). The README covers this for v1.
- **E5 — Date archives / weekly digest email.** RSS covers freshness for v1.
- **Launch checklist (Pavel/Vicky, outside this repo):** link from
  lenz.io/developers; `@isthisbs` bot bio + reply links; Show HN post; domain
  DNS → Firebase (isthisbs.org); create GA4 property + set `GA_MEASUREMENT_ID`.
- **Lenz-side API extension (Lenz repo, separate PR):** make
  `GET /verifications/{id}/related` keyless public-read (list + detail already
  are; verified 2026-07-23). Until then the site uses entity-overlap fallback
  for MORE CHECKS. Second candidate: `modified_since` incremental catalog feed.
- **Future interactivity (votes/comments/challenges):** Firestore + anonymous
  auth + lazy JS islands; nightly build bakes aggregates back into static HTML.
  See PROJECT_BRIEF.md → "Future: interactivity layer".
