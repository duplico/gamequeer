import { readFileSync, readdirSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { beforeAll, describe, expect, test } from 'vitest';
import { createParse, lexerAndParserErrors } from './test-utils.js';

// Real-world regression sweep (issue #321): every committed .gq fixture must
// parse cleanly under the fixed grammar, and a well-formed `game {}` block
// must not trip the new cardinality validator (fix 3).
const TEST_DIR = fileURLToPath(new URL('.', import.meta.url));
const REPO_ROOT = join(TEST_DIR, '..', '..');
const FIXTURE_DIRS = [
    join(REPO_ROOT, 'gamequeer', 'tests', 'golden'),
    join(REPO_ROOT, 'examples', 'games')
];

function findGqFiles(dir: string): string[] {
    return readdirSync(dir)
        .filter(f => f.endsWith('.gq'))
        .map(f => join(dir, f));
}

const fixtures = FIXTURE_DIRS.flatMap(findGqFiles).map(path => ({
    path,
    label: relative(REPO_ROOT, path)
}));

let parse: ReturnType<typeof createParse>;

beforeAll(() => {
    parse = createParse();
    // Sanity check: if this ever goes to zero, the glob above is broken, not
    // the fixtures.
    expect(fixtures.length).toBeGreaterThan(0);
});

describe('golden/example .gq fixtures parse and validate cleanly', () => {
    test.each(fixtures)('$label', async ({ path }) => {
        const text = readFileSync(path, 'utf-8');
        const document = await parse(text, { validation: true });

        expect(lexerAndParserErrors(document)).toEqual([]);

        const errorDiagnostics = (document.diagnostics ?? [])
            .filter(d => d.severity === 1) // DiagnosticSeverity.Error
            .map(d => d.message);
        expect(errorDiagnostics).toEqual([]);
    });
});
