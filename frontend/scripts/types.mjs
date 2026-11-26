import { readFile, writeFile } from "node:fs/promises";
import openapiTS, { astToString, COMMENT_HEADER } from "openapi-typescript";

const schema = new URL("../src/api/openapi.json", import.meta.url);
const target = new URL("../src/api/schema.d.ts", import.meta.url);
const generated = `${COMMENT_HEADER}${astToString(await openapiTS(schema))}`;

if (process.argv.includes("--check")) {
  const current = await readFile(target, "utf8").catch(() => "");
  if (current !== generated) {
    console.error("src/api/schema.d.ts şemayla aynı değil; `make openapi` ile yeniden üret.");
    process.exit(1);
  }
} else {
  await writeFile(target, generated, "utf8");
}
