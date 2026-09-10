import test from "node:test";
import assert from "node:assert/strict";
import {
  comparisonIssue,
  controller,
  outcomeMessage,
} from "../flybet/web/insights.js";

test("missing wins do not become a zero-percent or risk-taking claim", () => {
  assert.match(outcomeMessage(null), /Complete a decision/);
  const metrics = {
    decisions: 10,
    conditions: { win: { events: 0, next_n: 0 }, loss: { next_n: 9 } },
  };
  assert.match(outcomeMessage(metrics), /No wins recorded/);
  metrics.conditions.win.events = 1;
  assert.match(outcomeMessage(metrics), /No win has a following/);
  metrics.conditions.win.next_n = 1;
  metrics.next_spin_difference = 0.25;
  assert.match(outcomeMessage(metrics), /\+25 percentage points/);
  assert.match(outcomeMessage(metrics), /association/);
});

test("comparison requires compatible conditions and verified model identity", () => {
  const a = {
    run_id: "a",
    metrics: {},
    model_identity: "same",
    config: {
      scenario: "fly",
      stake_cents: 100,
      bankroll_cents: 10000,
      max_decisions: 100,
      learning: true,
      policy: "neural",
    },
  };
  const b = structuredClone(a);
  assert.match(comparisonIssue(a, b), /different reference/);
  b.run_id = "b";
  b.config.learning = false;
  assert.equal(comparisonIssue(a, b), "");
  b.config.scenario = "house";
  assert.match(comparisonIssue(a, b), /same odds/);
  b.config.scenario = "fly";
  b.model_identity = null;
  assert.match(comparisonIssue(a, b), /identities/);
  assert.match(
    controller({ policy: "random-baseline", learning: true }),
    /Random baseline/,
  );
  assert.match(controller({ policy: "neural", learning: false }), /frozen/);
});
