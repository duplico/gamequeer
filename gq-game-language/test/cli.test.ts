import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { runLint } from '../src/cli/program.js';

// A minimal, well-formed `game { ... }` block, matching test-utils.ts's
// VALID_GAME_BLOCK -- parses and validates cleanly.
const CLEAN_FIXTURE = `
game {
    id = 0;
    title := "Test Game";
    author := "duplico";
    starting_stage = start;
}
stage start {
}
`;

// A second, independently-clean fixture (different game id/title) -- used to
// prove the multi-file case reports per-file, not just "any error anywhere".
const CLEAN_FIXTURE_2 = `
game {
    id = 1;
    title := "Another Game";
    author := "duplico";
    starting_stage = start;
}
stage start {
}
`;

// Trips the game-block cardinality validator's duplicate-key check
// (game-queer-game-language-validator.ts) at a precisely known location: the
// duplicate 'id = 1;' assignment is line 4 (1-based), starting at column 5
// (four leading spaces).
const DUPLICATE_ID_FIXTURE = `
game {
    id = 0;
    id = 1;
    title := "Test Game";
    author := "duplico";
    starting_stage = start;
}
stage start {
}
`;
const DUPLICATE_ID_LINE = 4;
const DUPLICATE_ID_COLUMN = 5;

// Trips only the reserved-builtin *warning* path (assigning a writable
// builtin doesn't warn, but nothing here trips an error either) -- used for
// the --strict test. GQI_PLAYER_ID is read-only, so assigning it warns
// without being an error.
const WARNING_ONLY_FIXTURE = `
game {
    id = 0;
    title := "Test Game";
    author := "duplico";
    starting_stage = start;
}
stage start {
    event enter {
        GQI_PLAYER_ID = 5;
    }
}
`;

function writeFixture(dir: string, name: string, contents: string): string {
    const filePath = join(dir, name);
    writeFileSync(filePath, contents, 'utf-8');
    return filePath;
}

describe('runLint', () => {
    let dir: string;
    let logLines: string[];
    let logSpy: ReturnType<typeof vi.spyOn>;
    let errorSpy: ReturnType<typeof vi.spyOn>;

    beforeEach(() => {
        dir = mkdtempSync(join(tmpdir(), 'gq-lang-lint-cli-test-'));
        logLines = [];
        logSpy = vi.spyOn(console, 'log').mockImplementation((line: string) => {
            logLines.push(line);
        });
        errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    });

    afterEach(() => {
        logSpy.mockRestore();
        errorSpy.mockRestore();
        rmSync(dir, { recursive: true, force: true });
    });

    test('a clean file exits 0 and reports zero errors', async () => {
        const file = writeFixture(dir, 'clean.gq', CLEAN_FIXTURE);

        const exitCode = await runLint([file]);

        expect(exitCode).toBe(0);
        expect(logLines.some(line => /: error:/.test(line))).toBe(false);
        expect(logLines).toContainEqual('0 error(s), 0 warning(s) in 1 file checked.');
    });

    test('a file with a validation error exits non-zero and reports the correct file:line:col', async () => {
        const file = writeFixture(dir, 'duplicate-id.gq', DUPLICATE_ID_FIXTURE);

        const exitCode = await runLint([file]);

        expect(exitCode).toBe(1);
        expect(logLines).toContainEqual(
            `${file}:${DUPLICATE_ID_LINE}:${DUPLICATE_ID_COLUMN}: error: Duplicate 'id' assignment in game block; exactly one is allowed.`
        );
        expect(logLines).toContainEqual('1 error(s), 0 warning(s) in 1 file checked.');
    });

    test('linting multiple files reports each file\'s diagnostics independently', async () => {
        const clean = writeFixture(dir, 'clean.gq', CLEAN_FIXTURE_2);
        const broken = writeFixture(dir, 'duplicate-id.gq', DUPLICATE_ID_FIXTURE);

        const exitCode = await runLint([clean, broken]);

        expect(exitCode).toBe(1);
        // The broken file's diagnostic is reported...
        expect(logLines).toContainEqual(
            `${broken}:${DUPLICATE_ID_LINE}:${DUPLICATE_ID_COLUMN}: error: Duplicate 'id' assignment in game block; exactly one is allowed.`
        );
        // ...and the clean file contributes no diagnostic of its own.
        expect(logLines.some(line => line.startsWith(clean) && / error: | warning: /.test(line))).toBe(false);
        expect(logLines).toContainEqual('1 error(s), 0 warning(s) in 2 files checked.');
    });

    test('a usage error (no such file) exits 2 without touching the language service', async () => {
        const missing = join(dir, 'does-not-exist.gq');

        const exitCode = await runLint([missing]);

        expect(exitCode).toBe(2);
        expect(errorSpy).toHaveBeenCalledWith(expect.stringContaining(missing));
    });

    test('--strict escalates a warning-only file to a non-zero exit code', async () => {
        const file = writeFixture(dir, 'warning-only.gq', WARNING_ONLY_FIXTURE);

        const lenientExitCode = await runLint([file]);
        expect(lenientExitCode).toBe(0);
        expect(logLines.some(line => / warning: /.test(line))).toBe(true);

        logLines.length = 0;
        const strictExitCode = await runLint([file], { strict: true });
        expect(strictExitCode).toBe(1);
    });
});
