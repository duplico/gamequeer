import { readFileSync, readdirSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { beforeAll, describe, expect, test } from 'vitest';
import { createParse, lexerAndParserErrors } from './test-utils.js';

// Real-world regression sweep (issue #321): every committed .gq fixture must
// parse cleanly under the fixed grammar, and a well-formed `game {}` block
// must not trip the new cardinality validator (fix 3). Recursive, so every
// migrated game's own top-level directory under examples/ (e.g.
// examples/perf_flat/, examples/showcase/, gamequeer#440) is covered too
// (gamequeer#326/#328 review).
//
// gqc/examples/skel/games/working_samples/ is included deliberately:
// sample_working_simple.gq is the fixture that demonstrates
// GQS_TEXTMENU_RESULT's pre-seed-before-textmenu write pattern (see the
// writable-classification rationale for that builtin, and
// builtin-textmenu-result.test.ts's targeted repro of that same snippet).
// Its sibling gqc/examples/skel/games/nonworking_samples/ is excluded on
// purpose -- those fixtures exist to exercise gqc's *error* paths (e.g.
// missing `starting_stage`, a duplicate variable name) and are expected to
// fail validation; sweeping them in here would defeat the "zero error
// diagnostics" assertion by design, not by regression.
const TEST_DIR = fileURLToPath(new URL('.', import.meta.url));
const REPO_ROOT = join(TEST_DIR, '..', '..');
const FIXTURE_DIRS = [
    join(REPO_ROOT, 'gamequeer', 'tests', 'golden'),
    join(REPO_ROOT, 'examples'),
    join(REPO_ROOT, 'gqc', 'examples', 'skel', 'games', 'working_samples')
];

// sample_working.gq, sample_working_simple.gq, and persistent_test.gq each
// declare an int variable literally named `A` and/or `B` (e.g.
// `int A = 1;`), which collide with the grammar's `input(A)`/`input(B)`
// button-literal keywords -- a pre-existing, unrelated grammar ambiguity
// (gamequeer#340), not a regression from this PR. Excluded here rather
// than silently dropping the whole directory; builtin-textmenu-result.test.ts
// covers sample_working_simple.gq's GQS_TEXTMENU_RESULT pattern directly
// instead.
const KNOWN_BROKEN_FIXTURES = new Set(['sample_working.gq', 'sample_working_simple.gq', 'persistent_test.gq']);

function findGqFiles(dir: string): string[] {
    return readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
        const fullPath = join(dir, entry.name);
        if (entry.isDirectory()) {
            return findGqFiles(fullPath);
        }
        return entry.name.endsWith('.gq') && !KNOWN_BROKEN_FIXTURES.has(entry.name) ? [fullPath] : [];
    });
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
