// The committed web/index.html must be exactly what `npm run build` makes from web/app today:
// a generated file that drifted from its source would ship code nobody reviewed.
import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
const WEB = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
// Both generated files: the page, and the CSP that pins its scripts by hash.
const targets = ["index.html", "vercel.json"].map((f) => path.join(WEB, f));
const read = (f) => (fs.existsSync(f) ? fs.readFileSync(f, "utf8") : "");
const before = targets.map(read);
execSync("npm run build --silent", { cwd: WEB, stdio: ["ignore", "ignore", "inherit"] });
const stale = targets.filter((f, i) => read(f) !== before[i]).map((f) => path.relative(WEB, f));
if (stale.length) {
  console.error(`web/${stale.join(" and web/")} did not match a fresh build of web/app; rebuilt now. Commit the result.`);
  process.exit(1);
}
console.log("web/index.html and web/vercel.json match a fresh build of web/app");
