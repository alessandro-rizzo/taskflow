import { writeFileSync } from "node:fs";

export type Argument = {
  name: string;
  type: string;
  enum?: string[];
  default?: unknown;
  required: boolean;
};

export type Output = {
  id: string;
  type: string;
  optional: boolean;
};

type Operation = {
  id: string;
  description: string;
  arguments: Argument[];
  outputs: Output[];
  required_effects: string[];
  required_capabilities: string[];
  body: () => never;
};

export type Schema = {
  document_kind: "schema";
  format_version: "t1-plan-conformance-schema-v1";
  fixture_id: string;
  fixture_version: string;
  status: string;
  operations: Omit<Operation, "body">[];
};

export type Diagnostic = {
  operation: string;
  path: string;
  expected: string;
  actual: unknown;
  human: string;
};

export interface BackendBinary {
  readonly __backendBinary: unique symbol;
}
export interface IOSApp {
  readonly __iosApp: unique symbol;
}
export interface API {
  readonly __api: unique symbol;
}
export interface OtherAPI {
  readonly __otherAPI: unique symbol;
}

export class Artifact<T> {
  private invariant!: (value: T) => T;
}

export class Endpoint<T> {
  private invariant!: (value: T) => T;
}

class Handle<T> {
  private invariant!: (value: T) => T;
  constructor(readonly id: string) {}
}

type Source = { readonly source: unique symbol };
type Check = { readonly check: unique symbol };
type GoTests = { readonly goTests: unique symbol };
type Report<T> = { readonly report: T };
type Diagnostics = { readonly diagnostics: unique symbol };

type TraceOutput = {
  id: string;
  from?: string;
  type: string;
  optional: boolean;
};

type TraceWork = {
  id: string;
  type: string;
  consumes: string[];
  produces: TraceOutput[];
};

export type Trace = {
  status: "experiment-only-not-plan-ir";
  execution: "fake";
  composition_rule: string;
  source: { id: string; type: "Source" };
  child_work: TraceWork[];
  aggregate: {
    id: string;
    type: "Check";
    depends_on: string[];
    exposes: TraceOutput[];
  };
  typed_handle_relations: { from: string; to: string }[];
};

class TraceBuilder {
  private readonly children: TraceWork[] = [];
  private readonly relations: { from: string; to: string }[] = [];

  source(): Handle<Source> {
    return new Handle<Source>("source");
  }

  child<I, O>(id: string, type: string, input: Handle<I>): Handle<O> {
    this.children.push({ id, type, consumes: [input.id], produces: [] });
    this.relations.push({ from: input.id, to: id });
    return new Handle<O>(id);
  }

  aggregate(
    format: Handle<Check>,
    tests: Handle<Report<GoTests>>,
    lint: Handle<Check>,
  ): Handle<Check> {
    for (const input of [format, tests, lint]) {
      this.relations.push({ from: input.id, to: "check" });
    }
    return new Handle<Check>("check");
  }

  finish(testReport: TraceOutput, diagnostics: TraceOutput): Trace {
    const test = this.children.find((child) => child.id === "test");
    if (test === undefined) {
      throw new Error("W1 trace requires test child");
    }
    test.produces = [{ ...testReport, from: undefined }];
    return {
      status: "experiment-only-not-plan-ir",
      execution: "fake",
      composition_rule: "dependencies are authored by passing typed handles, not only string identifiers",
      source: { id: "source", type: "Source" },
      child_work: this.children,
      aggregate: {
        id: "check",
        type: "Check",
        depends_on: ["format", "test", "lint"],
        exposes: [testReport, diagnostics],
      },
      typed_handle_relations: this.relations,
    };
  }
}

function requiredOutput<T>(id: string, from: Handle<T>, type: string): TraceOutput {
  return { id, from: from.id, type, optional: false };
}

function optionalOutput<T>(id: string, from: Handle<T>, type: string): TraceOutput {
  return { id, from: from.id, type, optional: true };
}

function neverRun(scope: string): () => never {
  return () => {
    const path = process.env.E01_BODY_SENTINEL;
    if (path !== undefined) {
      writeFileSync(path, scope, { mode: 0o600 });
    }
    throw new Error(`E01 operation body evaluated during discovery: ${scope}`);
  };
}

function operation(
  fixtureId: string,
  fixtureVersion: string,
  status: string,
  value: Operation,
): Schema {
  const { body: _body, ...publicValue } = value;
  return {
    document_kind: "schema",
    format_version: "t1-plan-conformance-schema-v1",
    fixture_id: fixtureId,
    fixture_version: fixtureVersion,
    status,
    operations: [publicValue],
  };
}

// E01-AUTHOR-BEGIN
export function composeW1(): Trace {
  const trace = new TraceBuilder();
  const source = trace.source();
  const format = trace.child<Source, Check>("format", "Check", source);
  const tests = trace.child<Source, Report<GoTests>>("test", "Report[GoTests]", source);
  const lint = trace.child<Source, Check>("lint", "Check", source);
  const check = trace.aggregate(format, tests, lint);
  return trace.finish(
    requiredOutput("test-report", tests, "Report[GoTests]"),
    optionalOutput("diagnostics", check, "Report[Diagnostics]"),
  );
}

const w1 = operation(
  "w1-fast-project-check",
  "t1-experimental-v1",
  "experimental",
  {
    id: "check",
    description: "Format check, unit tests, and static analysis, aggregated into one pass/fail Check.",
    arguments: [
      {
        name: "verbosity",
        type: "string",
        enum: ["quiet", "normal", "verbose"],
        default: "normal",
        required: false,
      },
      {
        name: "changed-only",
        type: "boolean",
        default: false,
        required: false,
      },
    ],
    outputs: [
      { id: "test-report", type: "Report[GoTests]", optional: false },
      { id: "diagnostics", type: "Report[Diagnostics]", optional: true },
    ],
    required_effects: [],
    required_capabilities: ["filesystem-read"],
    body: neverRun("W1"),
  },
);
// E01-AUTHOR-END

const w2 = operation(
  "w2-cross-target-artifact-pipeline",
  "t1-w2-experimental-v1",
  "experimental",
  {
    id: "build-and-verify",
    description: "Build the backend binary on Linux, run its Go test suite on a compatible Linux worker, and produce a local inspection summary.",
    arguments: [],
    outputs: [
      { id: "backend-binary", type: "Artifact[BackendBinary]", optional: false },
      { id: "go-tests-report", type: "Report[GoTests]", optional: false },
      { id: "inspection-summary", type: "LocalInspection", optional: false },
    ],
    required_effects: [],
    required_capabilities: ["linux-execution-profile"],
    body: neverRun("W2"),
  },
);

const w3 = operation(
  "w3-isolated-native-mobile-stack",
  "t1-w3-fixture-v1-experimental",
  "experimental",
  {
    id: "mobile-e2e",
    description: "Bring up a namespace-private Linux API stack, build the iOS app on macOS/Xcode, and run the end-to-end suite against a simulator.",
    arguments: [],
    outputs: [{ id: "mobile-e2e-report", type: "Report[MobileE2E]", optional: false }],
    required_effects: [],
    required_capabilities: [
      "linux-execution-profile",
      "macos-execution-profile",
      "simulator-session",
    ],
    body: neverRun("W3"),
  },
);

const effect = operation(
  "e01-effect-probe",
  "e01-effect-probe-v1",
  "experimental-synthetic",
  {
    id: "publish-preview",
    description: "Describe a policy-gated release publication without evaluating or authorizing its operation body.",
    arguments: [
      {
        name: "environment",
        type: "string",
        enum: ["staging", "production"],
        required: true,
      },
      {
        name: "channel",
        type: "string",
        enum: ["beta", "stable"],
        default: "beta",
        required: false,
      },
    ],
    outputs: [{ id: "published-release", type: "Effect[PublishedRelease]", optional: false }],
    required_effects: ["publish-release"],
    required_capabilities: ["network:app-store-connect", "secret:app-store-signing"],
    body: neverRun("effect"),
  },
);

const schemas: Record<string, Schema> = { W1: w1, W2: w2, W3: w3, effect };

export function discover(scope: string): Schema {
  const schema = schemas[scope];
  if (schema === undefined) {
    throw new Error(`unknown scope ${JSON.stringify(scope)}`);
  }
  return schema;
}

export function validate(scope: string, values: Record<string, unknown>): Diagnostic | undefined {
  const schema = discover(scope);
  const candidate = schema.operations[0];
  if (candidate === undefined) {
    throw new Error(`scope ${scope} has no operation`);
  }
  const known = new Map(candidate.arguments.map((argument) => [argument.name, argument]));
  for (const key of Object.keys(values).sort()) {
    if (!known.has(key)) {
      return diagnostic(candidate.id, key, "known argument", values[key]);
    }
  }
  for (const argument of candidate.arguments) {
    const present = Object.prototype.hasOwnProperty.call(values, argument.name);
    const value = values[argument.name];
    if (!present) {
      if (argument.required) {
        return diagnostic(candidate.id, argument.name, `required ${argument.type}`, null);
      }
      continue;
    }
    if (argument.type === "string" && typeof value !== "string") {
      return diagnostic(candidate.id, argument.name, "string", value);
    }
    if (argument.type === "boolean" && typeof value !== "boolean") {
      return diagnostic(candidate.id, argument.name, "boolean", value);
    }
    if (argument.enum !== undefined && typeof value === "string" && !argument.enum.includes(value)) {
      return diagnostic(candidate.id, argument.name, `one of [${argument.enum.join(" ")}]`, value);
    }
  }
  return undefined;
}

function diagnostic(operationId: string, path: string, expected: string, actual: unknown): Diagnostic {
  return {
    operation: operationId,
    path,
    expected,
    actual,
    human: `operation ${operationId} argument ${path} expected ${expected}; got ${String(actual)}`,
  };
}

export function encode(value: unknown): string {
  return `${JSON.stringify(value, null, 2)}\n`;
}

export function acceptIOS(_artifact: Artifact<IOSApp>): void {}
export function connectOther(_endpoint: Endpoint<OtherAPI>): void {}
