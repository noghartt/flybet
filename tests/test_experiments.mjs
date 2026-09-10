import test from "node:test";
import assert from "node:assert/strict";
import {
  bankrollReadout,
  learningConclusion,
} from "../flybet/web/experiments.js";
import { comparisonIssue } from "../flybet/web/insights.js";
test("conditioning reports missing or negative evidence explicitly", () => {
  assert.match(learningConclusion(null), /No completed/);
  assert.match(
    learningConclusion({ conclusion: "learning-not-established" }),
    /not established/,
  );
  assert.match(
    learningConclusion({
      conclusion: "candidate-memory-dependent-choice-effect",
    }),
    /Candidate/,
  );
});
test("interventions prevent an ordinary matched comparison", () => {
  const a = {
    run_id: "a",
    metrics: {},
    model_identity: "same",
    config: { wager_mode: "adaptive" },
  };
  const b = { ...a, run_id: "b", interventions: [{ operation: "erase" }] };
  assert.match(comparisonIssue(a, b), /interventions/);
});

test("exploratory preset comparisons still require the same model source and graph", () => {
  const a = {
    run_id: "a",
    metrics: {},
    model_identity: "profile-a",
    source_identity: "same",
    config: {},
  };
  const b = { ...a, run_id: "b", model_identity: "profile-b" };
  assert.match(comparisonIssue(a, b), /identities/);
  assert.equal(comparisonIssue(a, b, true), "");
  b.source_identity = "different";
  assert.match(comparisonIssue(a, b, true), /identities/);
});

test("bankroll readout reconciles dollars and separates decision-time funds from the result", () => {
  const state = {
    game: {
      config: { bankroll_cents: 10000 },
      wagered_cents: 600,
      returned_cents: 3200,
      bankroll_cents: 12600,
    },
    decoder: {
      executed_action: "SPIN",
      executed_stake_cents: 400,
      bankroll_context: {
        applied: true,
        before_cents: 13000,
        profit_cents: 3000,
        gain: 1.3,
        unweighted_multiplier: 2,
        proposed_multiplier: 4,
      },
    },
  };
  let result = bankrollReadout(state);
  assert.equal(
    result.ledger,
    "$100.00 start − $6.00 wagered + $32.00 returned = $126.00 available.",
  );
  assert.match(result.decision, /used \$130.00/);
  assert.match(result.decision, /1.3× wager-margin/);
  assert.match(result.decision, /2× tier → weighted 4× tier → \$4.00/);
  state.decoder.executed_action = "WAIT";
  result = bankrollReadout(state);
  assert.match(result.decision, /WAIT; no wager/);
  assert.doesNotMatch(result.decision, /affordable wager/);
  state.decoder.bankroll_context = {
    applied: false,
    reason: "random-baseline",
  };
  assert.match(bankrollReadout(state).decision, /baseline.*bypassed/);
  assert.match(bankrollReadout({}).ledger, /No slot balance/);
});
