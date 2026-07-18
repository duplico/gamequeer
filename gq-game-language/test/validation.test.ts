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

describe('reserved builtin assignment validator (issue #326)', () => {
    test('warns on assignment to a read-only int builtin', async () => {
        const document = await parse(`
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
`, { validation: true });

        expect(lexerAndParserErrors(document)).toEqual([]);
        const diagnostics = document.diagnostics ?? [];
        expect(diagnostics).toHaveLength(1);
        expect(diagnostics[0].severity).toBe(2); // DiagnosticSeverity.Warning
        expect(diagnostics[0].message).toContain('GQI_PLAYER_ID');
        expect(diagnostics[0].message).toContain('read-only');
    });

    test('warns on assignment to a read-only str builtin', async () => {
        const document = await parse(`
game {
    id = 0;
    title := "Test Game";
    author := "duplico";
    starting_stage = start;
}
stage start {
    event enter {
        GQS_GAME_NAME := "hijacked";
    }
}
`, { validation: true });

        expect(lexerAndParserErrors(document)).toEqual([]);
        const diagnostics = document.diagnostics ?? [];
        expect(diagnostics).toHaveLength(1);
        expect(diagnostics[0].severity).toBe(2); // DiagnosticSeverity.Warning
        expect(diagnostics[0].message).toContain('GQS_GAME_NAME');
        expect(diagnostics[0].message).toContain('read-only');
    });

    test('does not warn on assignment to a writable builtin', async () => {
        const document = await parse(`
game {
    id = 0;
    title := "Test Game";
    author := "duplico";
    starting_stage = start;
}
stage start {
    event enter {
        GQI_LABEL1_X = 0;
        GQS_LABEL1 := "hi";
    }
}
`, { validation: true });

        expect(lexerAndParserErrors(document)).toEqual([]);
        expect(document.diagnostics ?? []).toEqual([]);
    });

    test('reading a read-only builtin (not assigning to it) produces no diagnostics', async () => {
        // GQI_PLAYER_ID is read-only, but only the *assignment target*
        // checks (checkIntAssignmentBuiltin/checkStrAssignmentBuiltin) look
        // at builtins -- a read (an IntOperand use, e.g. in a condition)
        // should never be flagged.
        const document = await parse(`
game {
    id = 0;
    title := "Test Game";
    author := "duplico";
    starting_stage = start;
}
stage start {
    event enter {
        if (GQI_PLAYER_ID == 1) {
        }
    }
}
`, { validation: true });

        expect(lexerAndParserErrors(document)).toEqual([]);
        expect(document.diagnostics ?? []).toEqual([]);
    });

    test('errors when an int builtin is assigned with := (kind mismatch)', async () => {
        const document = await parse(`
game {
    id = 0;
    title := "Test Game";
    author := "duplico";
    starting_stage = start;
}
stage start {
    event enter {
        GQI_LABEL1_X := "0";
    }
}
`, { validation: true });

        expect(lexerAndParserErrors(document)).toEqual([]);
        const diagnostics = document.diagnostics ?? [];
        expect(diagnostics).toHaveLength(1);
        expect(diagnostics[0].severity).toBe(1); // DiagnosticSeverity.Error
        expect(diagnostics[0].message).toContain('GQI_LABEL1_X');
        expect(diagnostics[0].message).toContain(':=');
    });

    test('errors when a str builtin is assigned with = (kind mismatch)', async () => {
        const document = await parse(`
game {
    id = 0;
    title := "Test Game";
    author := "duplico";
    starting_stage = start;
}
stage start {
    event enter {
        GQS_LABEL1 = 0;
    }
}
`, { validation: true });

        expect(lexerAndParserErrors(document)).toEqual([]);
        const diagnostics = document.diagnostics ?? [];
        expect(diagnostics).toHaveLength(1);
        expect(diagnostics[0].severity).toBe(1); // DiagnosticSeverity.Error
        expect(diagnostics[0].message).toContain('GQS_LABEL1');
    });
});
