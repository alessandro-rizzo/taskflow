import fs from "node:fs";
import ts from "typescript";

const path = process.argv[2];
if (path === undefined) {
  process.stderr.write("usage: format-source.mjs PATH\n");
  process.exit(2);
}
const input = fs.readFileSync(path, "utf8");
const source = ts.createSourceFile(path, input, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
if (source.parseDiagnostics.length > 0) {
  for (const diagnostic of source.parseDiagnostics) {
    process.stderr.write(ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n") + "\n");
  }
  process.exit(1);
}
const printer = ts.createPrinter({ newLine: ts.NewLineKind.LineFeed });
process.stdout.write(printer.printFile(source) + "\n");
