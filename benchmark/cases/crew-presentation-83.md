# Write the browser test that loads the sprint-overview page and asserts package data appears

As a **A reader of the crew's delivery history**, I want **the sprint-overview page to be verified in a real browser against the package's data**, so that **I know the numbers I see are the numbers the package carries, not stale or computed values**.

## Acceptance criteria

1. **Given** the build/ directory contains the rendered sprint-overview page and ./.package/ contains the fetched design-system stylesheet
   **When** the browser test loads the sprint-overview page and the package's sprint_metrics.answers for the sprint has throughput 22 and first_attempt_numerator 12 with first_attempt_denominator 22
   **Then** the page's DOM contains an element with the exact text '22' for stories delivered and an element with the exact text '12 of 22' for landed first try, and the design-system CSS is served from the local ./.package/ file (not fetched from the network)

2. **Given** the package's analysis.stories[] contains exactly 7 entries for the sprint
   **When** the browser test loads the sprint-overview page
   **Then** the attempt chart section contains exactly 7 story rows, each with a card number matching the package's analysis.stories[].card.number values in the same order

3. **Given** the package's sprints[] has exactly one entry (a single-sprint package)
   **When** the browser test loads the sprint-overview page
   **Then** the page renders without error, the header shows the sprint's name, and no JavaScript console errors are present

4. **Given** the design-system stylesheet URL in the page's <head> references https://cdn.jsdelivr.net/gh/mqucifer/design-system@v0.1.0/styles.css
   **When** the Playwright test intercepts that URL and serves the local file from ./.package/
   **Then** the page's computed styles resolve CSS custom properties (e.g. --color-bg) to the light-theme values and the page does not flash the dark theme before the stylesheet loads (the theme IIFE in <head> sets data-theme before paint)

<!-- crew:ux-criteria -->
*What the reader sees, added by the UX Designer:*

5. **Given** The build/ directory contains the rendered sprint-overview page and the browser test loads it
   **When** The page's <head> is inspected after load
   **Then** The <head> contains a <link> element whose href is exactly 'https://cdn.jsdelivr.net/gh/mqucifer/design-system@v0.1.0/styles.css' and a <link> element whose href is the site's own CSS path, and the theme IIFE script appears before both <link> elements in document order

6. **Given** The browser test loads the sprint-overview page from build/
   **When** The page's DOM is read after load completes
   **Then** The page contains exactly one element with the 'feature' class (the crew-decisions panel), exactly one element with the 'stats' class (the big-number row), and zero elements with the 'crew:placeholder' text

7. **Given** The package's sprints[] has exactly one entry and the browser test loads the sprint-overview page
   **When** The page renders
   **Then** No JavaScript console errors are logged, the document's <html> element has a data-theme attribute set to either 'light' or 'dark' (set by the IIFE before first paint), and the body's computed background colour matches the --color-bg value for the active theme
**Existing tests** — this story changes what they assert: tests/test_contracts.py::test_placeholder_checks_contain_marker

**Builds on** — [mqucifer/crew-presentation#73](https://github.com/mqucifer/crew-presentation/issues/73)

Follows the epic's R1.

**Estimate** — 3 points

---

Split from [mqucifer/crew-presentation#68](https://github.com/mqucifer/crew-presentation/issues/68) *(Render the sprint overview from the delivery-history package, to the design reference)* by the Business Analyst.