import { composeW1, discover, encode, validate } from "./candidate.ts";

const [command, ...arguments_] = process.argv.slice(2);

function fatal(message: string): never {
  process.stderr.write(`${message}\n`);
  process.exit(2);
}

if (command === "discover") {
  const scope = arguments_[0];
  if (scope === undefined || arguments_.length !== 1) {
    fatal("discover requires scope");
  }
  try {
    process.stdout.write(encode(discover(scope)));
  } catch (error) {
    fatal(error instanceof Error ? error.message : String(error));
  }
} else if (command === "trace") {
  process.stdout.write(encode(composeW1()));
} else if (command === "validate") {
  const [scope, payload] = arguments_;
  if (scope === undefined || payload === undefined || arguments_.length !== 2) {
    fatal("validate requires scope and JSON");
  }
  let values: Record<string, unknown>;
  try {
    const parsed: unknown = JSON.parse(payload);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      fatal("validation payload must be an object");
    }
    values = parsed as Record<string, unknown>;
  } catch (error) {
    fatal(error instanceof Error ? error.message : String(error));
  }
  const result = validate(scope, values);
  if (result !== undefined) {
    process.stderr.write(JSON.stringify(result) + "\n");
    process.stderr.write(result.human + "\n");
    process.exit(2);
  }
  process.stdout.write(encode({ valid: true }));
} else {
  fatal("usage: cli.ts discover SCOPE | trace | validate SCOPE JSON");
}
