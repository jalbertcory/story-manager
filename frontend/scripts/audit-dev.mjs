import { spawnSync } from "node:child_process";
import { readFileSync, realpathSync } from "node:fs";
import { pathToFileURL } from "node:url";

const advisory = "https://github.com/advisories/GHSA-fc5q-39xc-vjpf";
const expires = Date.parse("2026-12-01T00:00:00-05:00");
const path = "node_modules/picomatch";

// The production audit runs separately. This exception applies only to the
// locked development copy and to high findings inherited solely from it.
export function allowsPicomatch(report, packages, now = Date.now()) {
  const findings = report?.vulnerabilities;
  const pico = findings?.picomatch;
  if (
    now >= expires ||
    report?.error ||
    report?.auditReportVersion !== 2 ||
    pico?.severity !== "high" ||
    pico.nodes?.length !== 1 ||
    pico.nodes[0] !== path ||
    packages[path]?.version !== "4.0.7" ||
    packages[path]?.dev !== true ||
    pico.via?.length !== 1 ||
    pico.via[0]?.url !== advisory ||
    pico.via[0].name !== "picomatch" ||
    pico.via[0].severity !== "high"
  )
    return false;

  const counts = report.metadata?.vulnerabilities;
  const high = Object.values(findings).filter(
    (finding) => finding.severity === "high",
  );
  if (counts?.critical !== 0 || counts.high !== high.length) return false;

  const allowed = new Set(["picomatch"]);
  const belowThreshold = new Set(["info", "low", "moderate"]);
  function covered(name, visiting) {
    if (allowed.has(name)) return true;
    const finding = findings[name];
    if (
      finding?.severity !== "high" ||
      visiting.has(name) ||
      !Array.isArray(finding.via)
    )
      return false;
    const causes = finding.via.filter(
      (cause) =>
        typeof cause !== "string" ||
        !belowThreshold.has(findings[cause]?.severity),
    );
    if (
      !causes.length ||
      !causes.every(
        (cause) =>
          typeof cause === "string" &&
          covered(cause, new Set([...visiting, name])),
      )
    )
      return false;
    allowed.add(name);
    return true;
  }
  return Object.entries(findings).every(
    ([name, finding]) =>
      belowThreshold.has(finding.severity) || covered(name, new Set()),
  );
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(realpathSync(process.argv[1])).href
) {
  const result = spawnSync("npm", ["audit", "--json", "--audit-level=high"], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "inherit"],
  });
  if (result.error) throw result.error;
  const report = JSON.parse(result.stdout);
  if (result.status === 0 && !report.error && report.auditReportVersion === 2) {
    console.log("Development audit passed.");
  } else if (
    result.status === 1 &&
    allowsPicomatch(
      report,
      JSON.parse(readFileSync("package-lock.json")).packages,
    )
  ) {
    console.warn(
      `Development audit accepted ${advisory} for picomatch@4.0.7 until December 1, 2026 (Eastern).`,
    );
  } else {
    console.error(result.stdout);
    process.exitCode = 1;
  }
}
