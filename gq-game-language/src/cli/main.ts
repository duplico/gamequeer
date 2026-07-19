// Shebang is injected by esbuild.mjs's banner (this file is not itself
// directly executable pre-build).
import { CommanderError } from 'commander';
import { createCliProgram } from './program.js';

createCliProgram().parseAsync(process.argv).catch(error => {
    if (error instanceof CommanderError) {
        // exitOverride() (see program.ts) routes commander's own --help,
        // --version, and argument/option parsing errors here instead of
        // process.exit()-ing directly. --help/--version already carry the
        // right code (0); any other commander-level error (bad flag, missing
        // <patterns...>) is a CLI usage problem, same category as a bad path
        // -- normalize to runLint's "2" rather than commander's own default
        // of 1, which would be indistinguishable from "lint found errors".
        process.exitCode = error.exitCode === 0 ? 0 : 2;
        return;
    }
    // An actually unexpected failure (a bug, not a usage problem) -- don't
    // report it as a usage error.
    console.error(error);
    process.exitCode = 1;
});
