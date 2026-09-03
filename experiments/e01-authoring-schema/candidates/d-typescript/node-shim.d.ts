declare module "node:fs" {
  export function writeFileSync(path: string, data: string, options?: { mode?: number }): void;
}

declare const process: {
  argv: string[];
  env: Record<string, string | undefined>;
  stdout: { write(value: string): void };
  stderr: { write(value: string): void };
  exit(code: number): never;
};
