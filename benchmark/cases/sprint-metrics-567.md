# Add superseded metrics to the CLI single-sprint JSON response and schema

As a **script or dashboard consuming the JSON API**, I want **the --json output to include superseded_count, superseded_points, and superseded_breakdown**, so that **I can read the re-split data alongside throughput without a separate query**.

## Acceptance criteria

1. **Given** a cards file containing one completed card (created 2024-01-01, started 2024-01-02, completed 2024-01-05, points 5) and one superseded card (created 2024-01-01, started 2024-01-02, superseded true, superseded_because "sponsor", points 3)
   **When** the command is run with that file and --json
   **Then** stdout parses as a JSON object with "superseded_count" set to 1, "superseded_points" set to 3, and "superseded_breakdown" set to {"sponsor": 1, "story_problem": 0}, alongside the existing metric keys

2. **Given** a cards file containing an empty array
   **When** the command is run with that file and --json
   **Then** stdout parses as a JSON object with "superseded_count" set to 0, "superseded_points" set to 0, and "superseded_breakdown" set to {"sponsor": 0, "story_problem": 0}

3. **Given** a cards file containing one superseded card and one completed card, and the command is run with --json --metrics superseded_count,superseded_points,superseded_breakdown
   **When** the command completes
   **Then** the exit code is 0, the JSON object on stdout contains the keys "superseded_count", "superseded_points", "superseded_breakdown", "api_version", and "flags", and does NOT contain the key "cycle_time_days" or "throughput"

4. **Given** the command is run with --schema --json
   **When** stdout is parsed as a JSON object
   **Then** the "required" array includes the strings "superseded_count", "superseded_points", and "superseded_breakdown", and the "properties" object defines "superseded_count" with type ["integer", "null"], "superseded_points" with type ["integer", "null"], and "superseded_breakdown" with type ["object", "null"]

5. **Given** the command is run with --json --metrics superseded_count,bogus_metric
   **When** the command completes
   **Then** the exit code is 2, stderr contains the string "bogus_metric", and stdout is empty

6. **Given** a reader of docs/formats.md
   **When** they look for the description of the single-sprint JSON response fields
   **Then** they learn that the response includes a superseded_count field (integer, the number of superseded stories in the sprint), a superseded_points field (integer, the sum of points on superseded stories), and a superseded_breakdown field (object with "sponsor" and "story_problem" integer keys, the per-reason count), and that superseded stories are excluded from throughput and in-flight counts

<!-- crew:ux-criteria -->
*What the reader sees, added by the UX Designer:*

7. **Given** a cards file containing one completed card (created 2024-01-01, started 2024-01-02, completed 2024-01-05) and one superseded card (created 2024-01-01, started 2024-01-02, superseded true, superseded_because "sponsor", points 5)
   **When** the command is run with that file and --markdown
   **Then** the output contains the exact line "- **Superseded**: 1" positioned between the line "- **Blocked**: 0" and the line "## Current Sprint" in the Crew Performance Summary section

8. **Given** a cards file containing one card with "created": "2024-01-01", "superseded": true, "superseded_because": "story_problem", "points": 3, and no other cards
   **When** the command is run with that file and --json
   **Then** the JSON object on stdout has "throughput" equal to 0, "cycle_time_days" equal to 0, "points_delivered" equal to 0, "superseded_count" equal to 1, "superseded_points" equal to 3, and "superseded_breakdown" equal to {"sponsor": 0, "story_problem": 1}
**Existing tests** — unchanged: the new behaviour is opt-in

**Estimate** — 3 points

---

Split from [mqucifer/sprint-metrics#560](https://github.com/mqucifer/sprint-metrics/issues/560) *(Count superseded stories and points as a distinct metric in the API responses)* by the Business Analyst.