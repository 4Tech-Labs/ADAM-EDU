import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";

const assetsDir = path.resolve(process.cwd(), "dist", "assets");

if (!existsSync(assetsDir)) {
  throw new Error("dist/assets no existe. Ejecuta npm run build antes de validar el bundle.");
}

const assetNames = readdirSync(assetsDir).filter((name) => name.endsWith(".js"));

function findAsset(prefix) {
  const matches = assetNames.filter((name) => name.startsWith(`${prefix}-`));

  if (matches.length !== 1) {
    throw new Error(`Se esperaba exactamente un chunk con prefijo ${prefix}, encontrados: ${matches.join(", ") || "ninguno"}`);
  }

  return matches[0];
}

function readAsset(name) {
  return readFileSync(path.join(assetsDir, name), "utf8");
}

function listStaticImports(content) {
  return [...content.matchAll(/from"\.\/([^"]+)"/g)].map((match) => match[1]);
}

function assertMissing(imports, references, owner) {
  const leaked = references.filter((reference) => imports.some((entry) => entry.startsWith(reference)));

  if (leaked.length > 0) {
    throw new Error(`${owner} referencia chunks que deberian permanecer async: ${leaked.join(", ")}`);
  }
}

function assertContains(content, references, owner) {
  const missing = references.filter((reference) => !content.includes(reference));

  if (missing.length > 0) {
    throw new Error(`${owner} no conserva referencias async esperadas: ${missing.join(", ")}`);
  }
}

const indexAsset = findAsset("index");
const teacherLoginAsset = findAsset("TeacherLoginPage");
const casePreviewAsset = findAsset("CasePreview");
const m2Asset = findAsset("M2Eda");
const m3Asset = findAsset("M3AuditSection");
const m4Asset = findAsset("M4Finance");
const m5Asset = findAsset("M5ExecutiveReport");
const m6Asset = findAsset("M6MasterSolution");
const plotlyChartsRendererAsset = findAsset("PlotlyChartsRenderer");
const plotlyComponentAsset = findAsset("PlotlyComponent");

const indexContent = readAsset(indexAsset);
const teacherLoginContent = readAsset(teacherLoginAsset);
const casePreviewContent = readAsset(casePreviewAsset);
const m2Content = readAsset(m2Asset);
const plotlyChartsRendererContent = readAsset(plotlyChartsRendererAsset);

const indexImports = listStaticImports(indexContent);
const teacherLoginImports = listStaticImports(teacherLoginContent);

assertMissing(
  indexImports,
  ["CasePreview-", "M2Eda-", "M3AuditSection-", "M4Finance-", "M5ExecutiveReport-", "M6MasterSolution-", "PlotlyChartsRenderer-", "PlotlyComponent-"],
  indexAsset,
);
assertMissing(
  teacherLoginImports,
  ["CasePreview-", "M2Eda-", "M3AuditSection-", "M4Finance-", "M5ExecutiveReport-", "M6MasterSolution-", "PlotlyChartsRenderer-", "PlotlyComponent-"],
  teacherLoginAsset,
);
assertContains(casePreviewContent, [m2Asset, m3Asset, m4Asset, m5Asset, m6Asset], casePreviewAsset);
assertContains(m2Content, [plotlyChartsRendererAsset], m2Asset);
assertContains(plotlyChartsRendererContent, [plotlyComponentAsset], plotlyChartsRendererAsset);

console.log("Bundle isolation assertions passed.");
console.log(`Entry chunk: ${indexAsset}`);
console.log(`Teacher login chunk: ${teacherLoginAsset}`);
console.log(`Case preview chunk: ${casePreviewAsset}`);
console.log(`Plotly renderer chunk: ${plotlyChartsRendererAsset}`);
console.log(`Plotly component chunk: ${plotlyComponentAsset}`);