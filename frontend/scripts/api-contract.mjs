import { execFileSync } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import openapiTS, { astToString } from "openapi-typescript";
import ts from "typescript";

const root = fileURLToPath(new URL("../../", import.meta.url));
const python =
  process.env.PYTHON ||
  fileURLToPath(new URL("../../.venv/bin/python", import.meta.url));
const target = new URL("../src/api/schema.d.ts", import.meta.url);
const schema = execFileSync(python, ["-m", "backend.export_openapi"], {
  cwd: root,
  encoding: "utf8",
  maxBuffer: 16 * 1024 * 1024,
});
const nodes = await openapiTS(JSON.parse(schema), {
  alphabetize: true,
  transform(value) {
    if (
      value.type === "string" &&
      (value.format === "binary" ||
        value.contentMediaType === "application/octet-stream")
    ) {
      return ts.factory.createTypeReferenceNode("Blob");
    }
  },
});
const generated =
  "// Generated from FastAPI. Run npm run api:generate; do not edit.\n" +
  astToString(nodes);

if (process.argv.includes("--check")) {
  const existing = await readFile(target, "utf8").catch(() => "");
  if (existing !== generated) {
    console.error(
      "API contract is stale. Run npm run api:generate and commit src/api/schema.d.ts.",
    );
    process.exitCode = 1;
  } else {
    console.log("API contract matches the backend OpenAPI schema.");
  }
} else {
  await writeFile(target, generated);
  console.log("Generated src/api/schema.d.ts from the backend OpenAPI schema.");
}
