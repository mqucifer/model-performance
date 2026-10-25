# Reflow the stats row at phone width

As a **reader on a phone**, I want **the five sprint stats to wrap to multiple rows instead of being squeezed into one**, so that **each stat value is large enough to read and none is clipped**.

## Acceptance criteria

1. **Given** the built sprint-overview page with 5 stats (throughput, first-attempt, escalation, cycle-time, points)
   **When** the page is loaded in a browser at a 375px viewport
   **Then** the element with class 'stats' has a height greater than the height of a single '.stat' element (the stats wrap to at least 2 rows)

2. **Given** the built sprint-overview page with 5 stats
   **When** the page is loaded in a browser at a 375px viewport
   **Then** every element with class 'stat__value' has a scrollWidth equal to its parent's clientWidth (no stat value is horizontally clipped)

3. **Given** the built sprint-overview page with 5 stats
   **When** the page is loaded in a browser at a 1440px viewport
   **Then** all 5 elements with class 'stat' share the same top offset (they are in a single row, unchanged from desktop)

Follows the epic's R1.

<!-- crew:ux-criteria -->
*What the reader sees, added by the UX Designer:*

4. **Given** the built sprint-overview page with 5 stats where the package data yields values 22, '12 of 22', 1, 0.5, and 63
   **When** the page is loaded in a browser at a 375px viewport
   **Then** the five .stat__value elements, in document order, have text content '22', '12 of 22', '1', '0.5 days', and '63' respectively (the same values and order as at 1440px)

5. **Given** the built sprint-overview page with 5 stats
   **When** the page is loaded in a browser at a 375px viewport
   **Then** every .stat__value element has a computed font-size of at least 24px (the stat values are not shrunk below the --text-xl token to fit the phone)

6. **Given** the built sprint-overview page with 5 stats where the first stat's value is '22' and label is 'stories delivered'
   **When** the page is loaded in a browser at a 375px viewport
   **Then** the .stat__label element immediately following the .stat__value with text '22' has the exact text 'stories delivered' and its scrollWidth equals its clientWidth (the label is visible under its value, not clipped)

7. **Given** the built sprint-overview page with 5 stats
   **When** the page is loaded in a browser at a 1440px viewport
   **Then** all 5 .stat elements have the same computed top offset and the .stats element's height equals the height of a single .stat element (single row, unchanged from desktop)
**Estimate** — 2 points

---

Split from [mqucifer/crew-presentation#110](https://github.com/mqucifer/crew-presentation/issues/110) *(Read the sprint page as well on a phone as on a laptop)* by the Business Analyst.