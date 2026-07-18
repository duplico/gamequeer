import { beforeAll, describe, expect, test } from 'vitest';
import { createParse, lexerAndParserErrors } from './test-utils.js';

let parse: ReturnType<typeof createParse>;

beforeAll(() => {
    parse = createParse();
});

const STAGE = `
stage start {
}
`;

describe('game block cardinality validator (issue #321, fix 3)', () => {
    test('a well-formed game block (exactly one of each key) has no cardinality diagnostics', async () => {
        const document = await parse(`
game {
    id = 0;
    title := "Test Game";
    author := "duplico";
    starting_stage = start;
}
${STAGE}
`, { validation: true });

        expect(lexerAndParserErrors(document)).toEqual([]);
        expect(document.diagnostics ?? []).toEqual([]);
    });

    test('flags a missing author', async () => {
        const document = await parse(`
game {
    id = 0;
    title := "Test Game";
    starting_stage = start;
}
${STAGE}
`, { validation: true });

        expect(lexerAndParserErrors(document)).toEqual([]);
        const messages = (document.diagnostics ?? []).map(d => d.message);
        expect(messages).toEqual([expect.stringContaining("missing required assignment 'author'")]);
    });

    test('flags a duplicate id', async () => {
        const document = await parse(`
game {
    id = 0;
    id = 1;
    title := "Test Game";
    author := "duplico";
    starting_stage = start;
}
${STAGE}
`, { validation: true });

        expect(lexerAndParserErrors(document)).toEqual([]);
        const messages = (document.diagnostics ?? []).map(d => d.message);
        expect(messages).toEqual([expect.stringContaining("Duplicate 'id' assignment")]);
    });

    test('flags a game block missing author and containing a duplicate id together', async () => {
        const document = await parse(`
game {
    id = 0;
    id = 1;
    title := "Test Game";
    starting_stage = start;
}
${STAGE}
`, { validation: true });

        expect(lexerAndParserErrors(document)).toEqual([]);
        const messages = (document.diagnostics ?? []).map(d => d.message);
        expect(messages).toHaveLength(2);
        expect(messages.some(m => m.includes("Duplicate 'id' assignment"))).toBe(true);
        expect(messages.some(m => m.includes("missing required assignment 'author'"))).toBe(true);
    });
});
