import assert from "node:assert/strict";
import test from "node:test";
import { access, readFile, readdir } from "node:fs/promises";
import { extname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const workspace = fileURLToPath(new URL("../../../", import.meta.url));
const allowedGeometryRoots = ["packages/design-language/", "packages/composition-engine/", "packages/scene-graph/", "packages/pptx-export/"];

async function files(directory: string): Promise<string[]> {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(entries.map(async (entry): Promise<string[]> => {
    if (["dist", "node_modules"].includes(entry.name)) return [];
    const path = join(directory, entry.name);
    return entry.isDirectory() ? files(path) : [path];
  }));
  return nested.flat();
}

const propertyName = (node: ts.PropertyName | undefined) => node && ts.isIdentifier(node) ? node.text : node && ts.isStringLiteral(node) ? node.text : "";
const includesForbiddenSemanticDispatch = (node: ts.Expression) => {
  const text = node.getText();
  const readsSemanticField = /(?:\.(?:scenario|usageContext|audience|ageRange|title|headline|pageNumber|pageIndex|purpose|pageRole)\b|\b(?:scenario|usageContext|audience|ageRange|pageNumber|pageIndex|pageRole)\b)/i.test(text);
  const dispatchesOnValue = /(?:===|!==|==|!=|\.includes\s*\(|\.startsWith\s*\(|\.endsWith\s*\()/i.test(text);
  return readsSemanticField && dispatchesOnValue;
};
const includesGeometryDecision = (node: ts.Node) => /(?:bounds|layout|composition|candidate|tree|width|height|\bx\b|\by\b)/i.test(node.getText());

/** AST checks catch disguised templates that regex-only scanning misses. */
function inspectProductionFile(path: string, source: string): string[] {
  const relativePath = relative(workspace, path).replaceAll("\\", "/");
  const ast = ts.createSourceFile(path, source, ts.ScriptTarget.Latest, true);
  const failures: string[] = [];
  const report = (node: ts.Node, reason: string) => failures.push(`${relativePath}:${ast.getLineAndCharacterOfPosition(node.getStart()).line + 1} ${reason}`);
  const visit = (node: ts.Node) => {
    if (ts.isIfStatement(node) && includesForbiddenSemanticDispatch(node.expression) && includesGeometryDecision(node.thenStatement)) report(node, "semantic/business value dispatches to geometry or layout");
    if (ts.isSwitchStatement(node) && /(?:scenario|usageContext|audience|ageRange|title|headline|pageNumber|pageIndex|purpose|pageRole)/i.test(node.expression.getText()) && includesGeometryDecision(node.caseBlock)) report(node, "semantic/business value dispatches to geometry or layout");
    if (ts.isConditionalExpression(node) && includesForbiddenSemanticDispatch(node.condition) && (includesGeometryDecision(node.whenTrue) || includesGeometryDecision(node.whenFalse))) report(node, "semantic/business value dispatches to geometry or layout");
    if (ts.isArrayLiteralExpression(node) && node.elements.length >= 2 && node.elements.every((element) => ts.isObjectLiteralExpression(element) && ["x", "y", "width", "height"].every((key) => element.properties.some((property) => ts.isPropertyAssignment(property) && propertyName(property.name) === key)))) {
      report(node, "fixed coordinate-page answer array is forbidden");
    }
    if (ts.isClassDeclaration(node) && node.name?.text === "RelationConstraintCompiler") {
      const forbiddenReturn = node.members.some((member) => ts.isMethodDeclaration(member) && member.type && /Bounds|CompositionNode|SceneNode/.test(member.type.getText()));
      if (forbiddenReturn) report(node, "relation compiler may return constraints only");
    }
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && ["eval", "Function"].includes(node.expression.text)) report(node, "dynamic execution is forbidden");
    if (!allowedGeometryRoots.some((root) => relativePath.startsWith(root)) && ts.isPropertyAssignment(node) && ["x", "y", "width", "height"].includes(propertyName(node.name)) && ts.isNumericLiteral(node.initializer)) {
      report(node, "fixed geometry is outside an authorized geometry boundary");
    }
    ts.forEachChild(node, visit);
  };
  visit(ast);
  return failures;
}

test("production AST has no business-to-layout dispatch, fixed page answers, or generated-code execution", async () => {
  const roots = [join(workspace, "apps", "api", "src"), join(workspace, "packages")];
  const paths = (await Promise.all(roots.map(files))).flat().filter((file) => [".ts", ".tsx"].includes(extname(file)) && !file.endsWith(".test.ts") && !file.endsWith(".test.tsx"));
  const failures = (await Promise.all(paths.map(async (path) => inspectProductionFile(path, await readFile(path, "utf8"))))).flat();
  assert.deepEqual(failures, []);
});

test("production source contains no reference-deck vocabulary or embedded prompt prose", async () => {
  const roots = [join(workspace, "apps", "api", "src"), join(workspace, "packages")];
  const paths = (await Promise.all(roots.map(files))).flat().filter((file) => [".ts", ".tsx"].includes(extname(file)) && !file.endsWith(".test.ts") && !file.endsWith(".test.tsx"));
  const source = (await Promise.all(paths.map((file) => readFile(file, "utf8")))).join("\n");
  for (const pattern of [/森林动物大冒险/, /家长会模板/, /安全教育模板/, /Do not render words/i, /negative prompt/i, /new\s+Function\s*\(/i]) assert.equal(pattern.test(source), false, `forbidden production pattern: ${pattern}`);
});

test("application and domain layers do not import infrastructure", async () => {
  const roots = [join(workspace, "apps", "api", "src", "application"), join(workspace, "apps", "api", "src", "domain")];
  const paths = (await Promise.all(roots.map(files))).flat().filter((file) => extname(file) === ".ts");
  for (const path of paths) assert.equal(/from\s+["'][^"']*infrastructure/i.test(await readFile(path, "utf8")), false, `${relative(workspace, path)} imports infrastructure`);
});

test("public 008 schemas, ports, services, and adapters carry maintainable TSDoc", async () => {
  const roots = [join(workspace, "apps", "api", "src"), join(workspace, "packages")];
  const paths = (await Promise.all(roots.map(files))).flat().filter((file) => extname(file) === ".ts" && !file.endsWith(".test.ts") && !file.endsWith(".d.ts"));
  const missing: string[] = [];
  for (const path of paths) {
    const source = await readFile(path, "utf8");
    const ast = ts.createSourceFile(path, source, ts.ScriptTarget.Latest, true);
    for (const node of ast.statements) {
      const modifiers = ts.canHaveModifiers(node) ? ts.getModifiers(node) : undefined;
      if (!modifiers?.some((modifier) => modifier.kind === ts.SyntaxKind.ExportKeyword)) continue;
      const name = "name" in node && node.name && ts.isIdentifier(node.name as ts.Node) ? (node.name as ts.Identifier).text : ts.isVariableStatement(node) ? node.declarationList.declarations[0]?.name.getText() ?? "" : "";
      const governed = name.endsWith("Schema") || name.endsWith("Port") || name.endsWith("Service") || name.endsWith("UseCase") || name.endsWith("Adapter") || name === "RelationConstraintCompiler";
      if (governed && ts.getJSDocCommentsAndTags(node).length === 0) missing.push(`${relative(workspace, path)}:${ast.getLineAndCharacterOfPosition(node.getStart()).line + 1} ${name}`);
    }
  }
  assert.deepEqual(missing, []);
});

test("third-party reference repositories are not vendored into the runtime", async () => {
  let exists = true;
  try { await access(join(workspace, "third_party")); } catch { exists = false; }
  assert.equal(exists, false);
});
