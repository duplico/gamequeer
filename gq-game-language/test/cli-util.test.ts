import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { CliUsageError, formatDiagnostic, resolveGqFiles, severityLabel } from '../src/cli/cli-util.js';

describe('resolveGqFiles', () => {
    let dir: string;

    beforeEach(() => {
        dir = mkdtempSync(join(tmpdir(), 'gq-lang-lint-util-test-'));
    });

    afterEach(() => {
        rmSync(dir, { recursive: true, force: true });
    });

    test('resolves a single .gq file path', async () => {
        const file = join(dir, 'a.gq');
        writeFileSync(file, 'game {}');

        const resolved = await resolveGqFiles([file]);

        expect(resolved).toEqual([file]);
    });

    test('recursively walks a directory for .gq files, ignoring other extensions', async () => {
        writeFileSync(join(dir, 'a.gq'), 'game {}');
        mkdirSync(join(dir, 'sub'));
        writeFileSync(join(dir, 'sub', 'b.gq'), 'game {}');
        writeFileSync(join(dir, 'notes.txt'), 'not a game file');

        const resolved = await resolveGqFiles([dir]);

        expect(resolved.sort()).toEqual([join(dir, 'a.gq'), join(dir, 'sub', 'b.gq')].sort());
    });

    test('expands a glob pattern and drops non-.gq matches', async () => {
        writeFileSync(join(dir, 'a.gq'), 'game {}');
        writeFileSync(join(dir, 'b.gq'), 'game {}');
        writeFileSync(join(dir, 'readme.md'), '# not a game file');

        const resolved = await resolveGqFiles([join(dir, '*')]);

        expect(resolved.sort()).toEqual([join(dir, 'a.gq'), join(dir, 'b.gq')].sort());
    });

    test('deduplicates files matched by more than one argument', async () => {
        const file = join(dir, 'a.gq');
        writeFileSync(file, 'game {}');

        const resolved = await resolveGqFiles([file, dir]);

        expect(resolved).toEqual([file]);
    });

    test('throws a CliUsageError for a plain path that does not exist', async () => {
        await expect(resolveGqFiles([join(dir, 'missing.gq')])).rejects.toThrow(CliUsageError);
    });

    test('throws a CliUsageError for a plain file path with the wrong extension', async () => {
        const file = join(dir, 'notes.txt');
        writeFileSync(file, 'not a game file');

        await expect(resolveGqFiles([file])).rejects.toThrow(CliUsageError);
    });
});

describe('severityLabel', () => {
    test.each([
        [1, 'error'],
        [2, 'warning'],
        [3, 'info'],
        [4, 'hint'],
        [undefined, 'error']
    ] as const)('maps LSP severity %s to %s', (severity, label) => {
        expect(severityLabel(severity)).toBe(label);
    });
});

describe('formatDiagnostic', () => {
    test('formats as file:line:col: severity: message (1-based)', () => {
        const line = formatDiagnostic('/path/to/game.gq', {
            range: { start: { line: 2, character: 4 }, end: { line: 2, character: 10 } },
            severity: 1,
            message: 'something is wrong'
        });

        expect(line).toBe('/path/to/game.gq:3:5: error: something is wrong');
    });
});
