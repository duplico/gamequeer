import { URI } from 'langium';
import { NodeFileSystem } from 'langium/node';
import { Command } from 'commander';
import { createGameQueerGameLanguageServices } from '../language/game-queer-game-language-module.js';
import { CliUsageError, formatDiagnostic, resolveGqFiles, severityLabel } from './cli-util.js';

export interface LintOptions {
    /** Also exit non-zero when only warnings (no errors) were found. */
    strict?: boolean;
}

/**
 * Parses and validates the `.gq` files matched by `patterns` (file paths,
 * directory paths, and/or glob patterns -- see {@link resolveGqFiles}),
 * printing one `file:line:col: severity: message` line per diagnostic plus a
 * summary line.
 *
 * Runs the exact parse + validation pipeline the language server runs, just
 * without a VS Code/LSP connection, so `.gq` diagnostics are available
 * headlessly (CI, authors, AI harnesses).
 *
 * @returns the process exit code: `0` if clean (or only warnings without
 * `--strict`), `1` if any error diagnostics were found (or any diagnostics at
 * all under `--strict`), `2` for a CLI usage error (bad path, no matches).
 */
export async function runLint(patterns: string[], options: LintOptions = {}): Promise<number> {
    let files: string[];
    try {
        files = await resolveGqFiles(patterns);
    } catch (error) {
        if (error instanceof CliUsageError) {
            console.error(error.message);
            return 2;
        }
        throw error;
    }

    if (files.length === 0) {
        console.error('No .gq files matched the given arguments.');
        return 2;
    }

    const { shared } = createGameQueerGameLanguageServices(NodeFileSystem);
    const documents = await Promise.all(
        files.map(file => shared.workspace.LangiumDocuments.getOrCreateDocument(URI.file(file)))
    );
    await shared.workspace.DocumentBuilder.build(documents, { validation: true });

    let errorCount = 0;
    let warningCount = 0;

    for (const document of documents) {
        const filePath = document.uri.fsPath;
        for (const diagnostic of document.diagnostics ?? []) {
            if (severityLabel(diagnostic.severity) === 'error') {
                errorCount++;
            } else if (severityLabel(diagnostic.severity) === 'warning') {
                warningCount++;
            }
            console.log(formatDiagnostic(filePath, diagnostic));
        }
    }

    const fileWord = files.length === 1 ? 'file' : 'files';
    console.log(`${errorCount} error(s), ${warningCount} warning(s) in ${files.length} ${fileWord} checked.`);

    if (errorCount > 0) {
        return 1;
    }
    if (options.strict && warningCount > 0) {
        return 1;
    }
    return 0;
}

export function createCliProgram(): Command {
    const program = new Command();
    program
        .name('gq-lang-lint')
        .description('Parse and validate GameQueer .gq game-definition files headlessly (no VS Code required).')
        .argument('<patterns...>', 'files, directories, or glob patterns to lint, e.g. game.gq, games/, "games/**/*.gq"')
        .option('--strict', 'also exit non-zero when only warnings (no errors) were found', false)
        .action(async (patterns: string[], options: { strict: boolean }) => {
            process.exitCode = await runLint(patterns, options);
        });
    return program;
}
