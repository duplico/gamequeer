// Shebang is injected by esbuild.mjs's banner (this file is not itself
// directly executable pre-build).
import { createCliProgram } from './program.js';

createCliProgram().parseAsync(process.argv).catch(error => {
    console.error(error);
    process.exitCode = 2;
});
