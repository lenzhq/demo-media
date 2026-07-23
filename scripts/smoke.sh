#!/usr/bin/env bash
#
# smoke.sh — post-deploy verification of the live site.
#
# Encodes the launch checklist: content serving, catalog coverage, SEO/AEO
# assets, the claimlive function, cards, and (optionally) the domain redirect
# matrix. Runs in CI right after `firebase deploy` (see build-deploy.yml) and
# by hand via `make smoke-live`.
#
#   BASE_URL      origin to test              (default: https://isthisbs.org)
#   MIN_CLAIMS    minimum article count       (default: 1000)
#   CHECK_DOMAIN  apex domain for redirect checks; empty to skip
#                 (default: isthisbs.org when BASE_URL is the apex, else skip)
#
# Pure bash + curl + grep. Collects all failures before exiting non-zero.

set -uo pipefail

BASE_URL="${BASE_URL:-https://isthisbs.org}"
MIN_CLAIMS="${MIN_CLAIMS:-1000}"
if [[ -z "${CHECK_DOMAIN+x}" ]]; then
  if [[ "${BASE_URL}" == "https://isthisbs.org" ]]; then
    CHECK_DOMAIN="isthisbs.org"
  else
    CHECK_DOMAIN=""
  fi
fi

CURL="curl -s --max-time 45"
PASS=0
FAIL=0

ok()   { PASS=$((PASS + 1)); echo "  ok   $1"; }
bad()  { FAIL=$((FAIL + 1)); echo "  FAIL $1" >&2; }

check_status() { # url expected label
  local code
  code=$(${CURL} -o /dev/null -w '%{http_code}' "$1")
  [[ "${code}" == "$2" ]] && ok "$3 (${code})" || bad "$3 — got ${code}, want $2 ($1)"
}

echo "== smoke: ${BASE_URL} (min claims: ${MIN_CLAIMS}) =="

# --- 1. Core pages ---------------------------------------------------------
home=$(${CURL} "${BASE_URL}/")
grep -q '<title>' <<<"${home}" && ok "home serves a titled page" || bad "home missing <title>"
check_status "${BASE_URL}/latest/" 200 "latest feed"
check_status "${BASE_URL}/about/" 200 "about page"
check_status "${BASE_URL}/health/" 200 "section hub"

# --- 2. Catalog coverage ---------------------------------------------------
articles=$(${CURL} "${BASE_URL}/sitemap-articles.xml" | grep -o '<url>' | wc -l | tr -d ' ')
if [[ "${articles}" -ge "${MIN_CLAIMS}" ]]; then
  ok "sitemap carries ${articles} articles (>= ${MIN_CLAIMS})"
else
  bad "only ${articles} articles in sitemap (< ${MIN_CLAIMS})"
fi

# --- 3. SEO / AEO assets ---------------------------------------------------
children=$(${CURL} "${BASE_URL}/sitemap.xml" | grep -o '<loc>' | wc -l | tr -d ' ')
[[ "${children}" -ge 3 ]] && ok "sitemap index has ${children} children" || bad "sitemap index thin (${children})"
${CURL} "${BASE_URL}/llms.txt" | head -1 | grep -q '^# ' && ok "llms.txt populated" || bad "llms.txt missing/empty"
llms_full=$(${CURL} -I "${BASE_URL}/llms-full.txt" | grep -i content-length | grep -o '[0-9]*' | tr -d '\r')
[[ "${llms_full:-0}" -gt 100000 ]] && ok "llms-full.txt ${llms_full} bytes" || bad "llms-full.txt too small (${llms_full:-0})"
${CURL} "${BASE_URL}/robots.txt" | grep -q '^Sitemap:' && ok "robots points at sitemap" || bad "robots missing Sitemap"
${CURL} "${BASE_URL}/feed.xml" | grep -q '<entry>' && ok "atom feed has entries" || bad "atom feed empty"
check_status "${BASE_URL}/pagefind/pagefind.js" 200 "search index assets"

# --- 4. A real article: SERP contract + cards ------------------------------
article_path=$(${CURL} "${BASE_URL}/sitemap-articles.xml" \
  | grep -o '<loc>https://[^<]*</loc>' | head -1 \
  | sed -e 's|<loc>https://[^/]*||' -e 's|</loc>||')
vid=$(sed -n 's|.*-\([a-f0-9]\{8\}\)/$|\1|p' <<<"${article_path}")
if [[ -n "${article_path}" && -n "${vid}" ]]; then
  page=$(${CURL} "${BASE_URL}${article_path}")
  grep -q '<title>Fact Check: ' <<<"${page}" && ok "article title carries Fact Check + verdict" || bad "article title contract broken (${article_path})"
  grep -q 'content="Verdict: ' <<<"${page}" && ok "article description is verdict-first" || bad "article description contract broken"
  grep -q 'application/ld+json' <<<"${page}" && ok "article carries JSON-LD" || bad "article missing JSON-LD"
  check_status "${BASE_URL}/og/${vid}.png" 200 "static OG card"
  check_status "${BASE_URL}/c/${vid}/" 200 "/c/ short-link stub"
  ctype=$(${CURL} -o /dev/null -w '%{content_type}' "${BASE_URL}/og-live/${vid}.png")
  [[ "${ctype}" == image/png* ]] && ok "claimlive function renders cards" || bad "og-live not a png (${ctype})"
else
  bad "could not extract an article path/id from the sitemap"
fi

# --- 5. Not-found paths ----------------------------------------------------
check_status "${BASE_URL}/c/zzzzzzzz/" 404 "claimlive 404 for unknown id"
check_status "${BASE_URL}/definitely/not/a/page/" 404 "static 404"

# --- 6. Domain redirect matrix (skipped unless CHECK_DOMAIN set) -----------
if [[ -n "${CHECK_DOMAIN}" ]]; then
  for u in "http://${CHECK_DOMAIN}/" "http://www.${CHECK_DOMAIN}/" "https://www.${CHECK_DOMAIN}/"; do
    final=$(${CURL} -o /dev/null -L -w '%{url_effective}' "$u")
    [[ "${final}" == "https://${CHECK_DOMAIN}/" ]] && ok "redirect ${u} -> apex" || bad "redirect ${u} ended at ${final}"
  done
else
  echo "  (domain redirect matrix skipped — CHECK_DOMAIN empty)"
fi

echo "== smoke: ${PASS} passed, ${FAIL} failed =="
[[ "${FAIL}" -eq 0 ]]
