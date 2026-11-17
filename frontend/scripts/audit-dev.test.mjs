import assert from "node:assert/strict";
import test from "node:test";
import { allowsPicomatch } from "./audit-dev.mjs";

const path = "node_modules/picomatch";
const packages = { [path]: { version: "4.0.7", dev: true } };
const lastMinute = Date.parse("2026-12-01T04:59:59Z");
const report = {
  auditReportVersion: 2,
  metadata: { vulnerabilities: { high: 2, critical: 0 } },
  vulnerabilities: {
    picomatch: {
      severity: "high",
      nodes: [path],
      via: [
        {
          url: "https://github.com/advisories/GHSA-fc5q-39xc-vjpf",
          name: "picomatch",
          severity: "high",
        },
      ],
    },
    vite: { severity: "high", via: ["picomatch", "minimatch"] },
    minimatch: { severity: "moderate", via: [] },
  },
};

test("allows the exact advisory and its dependents until midnight Eastern", () => {
  assert.equal(allowsPicomatch(report, packages, lastMinute), true);
  assert.equal(allowsPicomatch(report, packages, lastMinute + 1000), false);
});

test("requires the locked development version", () => {
  for (const pkg of [{ version: "4.0.7" }, { version: "4.0.8", dev: true }]) {
    assert.equal(allowsPicomatch(report, { [path]: pkg }, lastMinute), false);
  }
});

test("blocks other causes and incomplete or failed audits", () => {
  for (const change of [
    (r) => r.vulnerabilities.picomatch.via.push({ severity: "high" }),
    (r) => {
      r.vulnerabilities.picomatch.via[0].url += "-other";
    },
    (r) => r.vulnerabilities.vite.via.push("unknown"),
    (r) => r.vulnerabilities.vite.via.push({ severity: "high" }),
    (r) => {
      r.vulnerabilities.vite.severity = "critical";
    },
    (r) => {
      r.metadata.vulnerabilities.high++;
    },
    (r) => {
      r.error = { code: "E503" };
    },
    (r) => {
      delete r.vulnerabilities;
    },
  ]) {
    const copy = structuredClone(report);
    change(copy);
    assert.equal(allowsPicomatch(copy, packages, lastMinute), false);
  }
});
