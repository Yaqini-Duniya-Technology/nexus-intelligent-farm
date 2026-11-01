from datetime import datetime, timezone


def parse_time(value):
    if not isinstance(value, str) or not value.strip():
        return None

    try:
        timestamp = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except ValueError:
        return None

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    return timestamp.astimezone(timezone.utc)


def retrieve_history(state, observation_id):
    observations = {
        row["id"]: row
        for row in state["observations"]
    }

    selected = observations.get(observation_id)

    if not selected:
        raise ValueError("Observation not found")

    cutoff = parse_time(selected.get("created"))

    if cutoff is None:
        raise ValueError(
            "Selected observation has an invalid submission time"
        )

    selected_time = parse_time(
        selected.get("observed_at") or selected.get("created")
    )

    if selected_time is None:
        raise ValueError(
            "Selected observation has an invalid observation time"
        )

    tasks = {
        row["observation_id"]: row
        for row in state["tasks"]
    }

    actions = {
        row["task_id"]: row
        for row in state.get("task_actions", [])
    }

    matches = []

    for previous in state["observations"]:
        if previous["id"] == selected["id"]:
            continue

        if previous["field_id"] != selected["field_id"]:
            continue

        if previous.get("category") != selected.get("category"):
            continue

        previous_created = parse_time(previous.get("created"))
        previous_observed = parse_time(
            previous.get("observed_at") or previous.get("created")
        )

        if previous_created is None or previous_observed is None:
            continue

        # Avoid using records submitted later or events observed
        # after the selected observation.
        if previous_created >= cutoff:
            continue

        if previous_observed > selected_time:
            continue

        task = tasks.get(previous["id"])

        if not task:
            continue

        eligible_reports = []

        for followup in state.get("followups", []):
            if followup["task_id"] != task["id"]:
                continue

            assessment = followup.get("evidence_assessment", {})

            # Fail closed when historical validation is unavailable.
            if assessment.get("eligible") is not True:
                continue

            recorded_at = parse_time(followup.get("recorded_at"))
            observed_at = parse_time(followup.get("observed_at"))

            if recorded_at is None or observed_at is None:
                continue

            if recorded_at > cutoff or observed_at > cutoff:
                continue

            eligible_reports.append({
                "id": followup["id"],
                "result": followup["result"],
                "evidence": followup.get(
                    "original_evidence",
                    followup["evidence"],
                ),
                "observed_at": followup["observed_at"],
                "recorded_at": followup["recorded_at"],
                "verification": "farmer_reported",
            })

        if not eligible_reports:
            continue

        eligible_reports.sort(
            key=lambda row: parse_time(row["recorded_at"]),
            reverse=True,
        )

        action = actions.get(task["id"])
        historical_action = None

        if action:
            performed_at = parse_time(action.get("performed_at"))
            recorded_at = parse_time(action.get("recorded_at"))

            if (
                performed_at is not None
                and recorded_at is not None
                and performed_at >= previous_observed
                and performed_at <= cutoff
                and recorded_at <= cutoff
            ):
                historical_action = {
                    "action_type": action["action_type"],
                    "description": action["description"],
                    "performed_at": action["performed_at"],
                }

        matches.append({
            "observation_id": previous["id"],
            "task_id": task["id"],
            "note": previous["note"],
            "observed_at": (
                previous.get("observed_at") or previous["created"]
            ),
            "action": historical_action,
            "followups": eligible_reports,
        })

    matches.sort(
        key=lambda row: parse_time(row["observed_at"]),
        reverse=True,
    )

    counts = {
        "improved": 0,
        "unchanged": 0,
        "worsened": 0,
        "uncertain": 0,
    }

    for match in matches:
        for report in match["followups"]:
            counts[report["result"]] += 1

    return {
        "selected_observation": selected,
        "knowledge_cutoff": selected["created"],
        "matching_observations": len(matches),
        "eligible_reports": sum(counts.values()),
        "reported_results": counts,
        "matches": matches,
        "retrieval_rule": "same-field-and-category-v1",
        "policy_effect": "descriptive_only",
        "explanation": (
            "Matches share the selected field and category. "
            "Only eligible reports available before submission "
            "of the selected observation are included. "
            "Matching does not establish the same diagnosis, "
            "treatment effectiveness or causation. "
            "Recommendations are unchanged."
        ),
    }


HISTORY_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>NEXUS · Field history</title>
    <style>
        * { box-sizing: border-box; }
        body {
            margin: 0;
            background: #f1f5ee;
            color: #183c2c;
            font: 16px system-ui, sans-serif;
        }
        header {
            background: #163f30;
            color: white;
            padding: 28px;
        }
        header a { color: white; }
        main {
            max-width: 1000px;
            margin: auto;
            padding: 24px;
        }
        section, article {
            background: white;
            border-radius: 14px;
            padding: 22px;
            margin-bottom: 18px;
            overflow-wrap: anywhere;
        }
        label { display: block; margin-bottom: 8px; }
        select, button {
            width: 100%;
            padding: 12px;
            border: 1px solid #bdcbbb;
            border-radius: 8px;
            font: inherit;
        }
        button {
            margin-top: 14px;
            color: white;
            background: #1d5c40;
            cursor: pointer;
        }
        button:disabled { opacity: .5; cursor: default; }
        .muted { color: #5d7060; }
        #message {
            padding: 12px;
            background: #fff1c6;
            border-radius: 8px;
            margin: 16px 0;
        }
        .report {
            border-left: 4px solid #6c8c4d;
            background: #f0f5eb;
            padding: 12px;
            margin-top: 12px;
        }
        select:focus-visible, button:focus-visible, a:focus-visible {
            outline: 3px solid #c8a12e;
            outline-offset: 3px;
        }
    </style>
</head>
<body>
    <header>
        <small>LOCAL PILOT · MILESTONE 4</small>
        <h1>NEXUS field history</h1>
        <a href="/">Back to farm workspace</a>
    </header>

    <main>
        <p class="muted">
            Retrieve earlier eligible reports from the same field
            and observation category.
        </p>

        <section>
            <form id="history-form">
                <label for="observation-id">
                    Select an observation
                </label>
                <select id="observation-id" required></select>
                <button id="retrieve" type="submit" disabled>
                    Retrieve earlier field history
                </button>
            </form>
        </section>

        <div id="message" role="status" aria-live="polite">
            Loading observations…
        </div>

        <div id="summary"></div>
        <div id="matches"></div>
    </main>

    <script>
        "use strict";

        const $ = id => document.getElementById(id);
        const node = (tag, text = "", className = "") => {
            const element = document.createElement(tag);
            element.textContent = text;
            element.className = className;
            return element;
        };

        function time(value) {
            return new Date(value).toLocaleString();
        }

        async function get(path) {
            const response = await fetch(path);
            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || "Request failed");
            }

            return data;
        }

        function renderHistory(data) {
            $("summary").replaceChildren();
            $("matches").replaceChildren();

            const summary = node("section");
            const counts = data.reported_results;

            summary.append(
                node("h2", "Retrieved evidence"),
                node(
                    "p",
                    `${data.matching_observations} earlier observations · ` +
                    `${data.eligible_reports} eligible reports`
                ),
                node(
                    "p",
                    `Improved: ${counts.improved} · ` +
                    `Unchanged: ${counts.unchanged} · ` +
                    `Worsened: ${counts.worsened} · ` +
                    `Uncertain: ${counts.uncertain}`
                ),
                node(
                    "p",
                    "Knowledge cutoff: " + time(data.knowledge_cutoff),
                    "muted"
                ),
                node("p", data.explanation, "muted")
            );

            $("summary").append(summary);

            if (!data.matches.length) {
                $("matches").append(
                    node(
                        "section",
                        "No earlier eligible field history was available " +
                        "for this observation."
                    )
                );
            }

            for (const match of data.matches) {
                const article = node("article");

                article.append(
                    node("h3", `Earlier observation #${match.observation_id}`),
                    node("p", match.note),
                    node("small", time(match.observed_at), "muted")
                );

                if (match.action) {
                    article.append(
                        node(
                            "p",
                            `Recorded action: ${match.action.action_type} · ` +
                            match.action.description
                        ),
                        node(
                            "small",
                            time(match.action.performed_at),
                            "muted"
                        )
                    );
                } else {
                    article.append(
                        node(
                            "p",
                            "No structured action record was available " +
                            "at the selected observation's submission time.",
                            "muted"
                        )
                    );
                }

                for (const report of match.followups) {
                    const block = node("div", "", "report");
                    block.append(
                        node("strong", `Reported ${report.result}`),
                        node("p", report.evidence),
                        node("small", time(report.observed_at), "muted"),
                        node(
                            "p",
                            "Farmer-reported evidence; effectiveness " +
                            "is not independently verified.",
                            "muted"
                        )
                    );
                    article.append(block);
                }

                $("matches").append(article);
            }
        }

        $("history-form").addEventListener("submit", async event => {
            event.preventDefault();
            $("retrieve").disabled = true;

            try {
                const id = $("observation-id").value;
                const data = await get(
                    "/api/history?observation_id=" + encodeURIComponent(id)
                );

                renderHistory(data);
                $("message").textContent = "History retrieved.";
            } catch (error) {
                $("message").textContent = error.message;
            } finally {
                $("retrieve").disabled = false;
            }
        });

        get("/api/state")
            .then(state => {
                const select = $("observation-id");
                select.replaceChildren(new Option("Select…", ""));

                for (const observation of state.observations) {
                    const field = state.fields.find(
                        row => row.id === observation.field_id
                    );

                    select.add(
                        new Option(
                            `#${observation.id} · ${field?.name || "Field"} · ` +
                            `${observation.category} · ${observation.note.slice(0, 60)}`,
                            observation.id
                        )
                    );
                }

                $("retrieve").disabled = !state.observations.length;
                $("message").textContent = state.observations.length
                    ? "Select an observation to retrieve its earlier history."
                    : "Record a field observation in the workspace first.";
            })
            .catch(error => {
                $("message").textContent = error.message;
            });
    </script>
</body>
</html>
"""