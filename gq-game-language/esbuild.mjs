//@ts-check
import * as esbuild from 'esbuild';
import * as fs from 'node:fs';

const watch = process.argv.includes('--watch');
const minify = process.argv.includes('--minify');

const success = watch ? 'Watch build succeeded' : 'Build succeeded';

function getTime() {
    const date = new Date();
    return `[${`${padZeroes(date.getHours())}:${padZeroes(date.getMinutes())}:${padZeroes(date.getSeconds())}`}] `;
}

function padZeroes(i) {
    return i.toString().padStart(2, '0');
}

const plugins = [{
    name: 'watch-plugin',
    setup(build) {
        build.onEnd(result => {
            if (result.errors.length === 0) {
                console.log(getTime() + success);
            }
        });
    },
}];

const ctx = await esbuild.context({
    // Entry points for the vscode extension and the language server
    entryPoints: ['src/extension/main.ts', 'src/language/main.ts'],
    outdir: 'out',
    bundle: true,
    target: "ES2017",
    // VSCode's extension host is still using cjs, so we need to transform the code
    format: 'cjs',
    // To prevent confusing node, we explicitly use the `.cjs` extension
    outExtension: {
        '.js': '.cjs'
    },
    loader: { '.ts': 'ts' },
    external: ['vscode'],
    platform: 'node',
    sourcemap: !minify,
    minify,
    plugins
});

// The headless CLI (issue #384) is built separately so it can carry a
// shebang banner and end up executable -- neither of which apply to the
// vscode-extension/language-server bundles above.
const cliPlugins = [{
    name: 'chmod-cli-plugin',
    setup(build) {
        build.onEnd(result => {
            if (result.errors.length === 0) {
                fs.chmodSync('out/cli/main.cjs', 0o755);
                console.log(getTime() + success);
            }
        });
    },
}];

const cliCtx = await esbuild.context({
    entryPoints: ['src/cli/main.ts'],
    // A lone entry point would otherwise flatten to out/main.cjs; pin
    // outbase so it lands at out/cli/main.cjs (matching package.json's
    // "bin" and langium-quickstart.md).
    outbase: 'src',
    outdir: 'out',
    bundle: true,
    target: "ES2017",
    format: 'cjs',
    outExtension: {
        '.js': '.cjs'
    },
    loader: { '.ts': 'ts' },
    banner: { js: '#!/usr/bin/env node' },
    platform: 'node',
    sourcemap: !minify,
    minify,
    plugins: cliPlugins
});

if (watch) {
    await ctx.watch();
    await cliCtx.watch();
} else {
    await ctx.rebuild();
    ctx.dispose();
    await cliCtx.rebuild();
    cliCtx.dispose();
}
