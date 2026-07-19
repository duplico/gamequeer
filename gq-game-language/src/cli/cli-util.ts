import * as fs from 'node:fs';
import * as path from 'node:path';
import fg from 'fast-glob';
import type { Diagnostic } from 'vscode-languageserver-types';

const GQ_EXTENSION = '.gq';

/** Raised for problems with the CLI's own arguments (bad path, wrong extension, no matches) -- as opposed to `.gq` diagnostics, which are reported, not thrown. */
export class CliUsageError extends Error {}

/**
 * Resolves the given CLI arguments -- file paths, directory paths, and/or
 * glob patterns -- to a deduplicated, sorted list of absolute `.gq` file
 * paths.
 *
 * - A glob pattern (per fast-glob's own `isDynamicPattern`, e.g. `*`, `**`,
 *   `{a,b}`) is expanded; matches without a `.gq` extension are silently
 *   dropped, since a broad pattern like `games/*` routinely sweeps up
 *   non-game files.
 * - A plain path to a directory is walked recursively for `.gq` files.
 * - A plain path to a file with a non-`.gq` extension is a hard usage error
 *   -- the caller almost certainly pointed the linter at the wrong file.
 * - A plain path that doesn't exist is a hard usage error.
 */
export async function resolveGqFiles(patterns: string[]): Promise<string[]> {
    const resolved = new Set<string>();

    for (const pattern of patterns) {
        if (fg.isDynamicPattern(pattern)) {
            const matches = await fg(pattern, { onlyFiles: true, absolute: true, dot: false });
            for (const match of matches) {
                if (match.endsWith(GQ_EXTENSION)) {
                    resolved.add(path.resolve(match));
                }
            }
            continue;
        }

        if (!fs.existsSync(pattern)) {
            throw new CliUsageError(`No such file or directory: ${pattern}`);
        }

        const stat = fs.statSync(pattern);
        if (stat.isDirectory()) {
            for (const file of walkDirectoryForGqFiles(pattern)) {
                resolved.add(path.resolve(file));
            }
        } else if (pattern.endsWith(GQ_EXTENSION)) {
            resolved.add(path.resolve(pattern));
        } else {
            throw new CliUsageError(`Not a ${GQ_EXTENSION} file: ${pattern}`);
        }
    }

    return [...resolved].sort();
}

function walkDirectoryForGqFiles(dir: string): string[] {
    return fs.readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
        const fullPath = path.join(dir, entry.name);
        if (entry.isDirectory()) {
            return walkDirectoryForGqFiles(fullPath);
        }
        return entry.name.endsWith(GQ_EXTENSION) ? [fullPath] : [];
    });
}

const SEVERITY_LABELS: Record<number, DiagnosticSeverityLabel> = {
    1: 'error',
    2: 'warning',
    3: 'info',
    4: 'hint'
};

export type DiagnosticSeverityLabel = 'error' | 'warning' | 'info' | 'hint';

/** Langium/LSP diagnostic severities are 1-4 (error/warning/info/hint); anything unset is treated as an error. */
export function severityLabel(severity: Diagnostic['severity']): DiagnosticSeverityLabel {
    return SEVERITY_LABELS[severity ?? 1] ?? 'error';
}

/**
 * Formats a single diagnostic in `file:line:col: severity: message` form
 * (1-based line/column, matching editors and other CLI tools such as `tsc`
 * and `eslint`) -- easy for both humans and CI/log-scraping tools to parse.
 */
export function formatDiagnostic(filePath: string, diagnostic: Diagnostic): string {
    const line = diagnostic.range.start.line + 1;
    const column = diagnostic.range.start.character + 1;
    return `${filePath}:${line}:${column}: ${severityLabel(diagnostic.severity)}: ${diagnostic.message}`;
}
