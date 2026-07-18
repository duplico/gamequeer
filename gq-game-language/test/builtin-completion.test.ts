import { beforeAll, describe, expect, test } from 'vitest';
import { textDocumentPositionParams } from 'langium/test';
import { GQ_RESERVED_INTS, GQ_RESERVED_STRS } from '../src/language/gq-builtins.js';
import { createParse, createTestServices, VALID_GAME_BLOCK } from './test-utils.js';

// Completion for reserved GQI_*/GQS_* builtins in identifier positions
// (gamequeer#326). The default CompletionProvider has nothing to offer for
// these positions at all (see game-queer-game-language-completion-provider.ts),
// so we only assert that our builtins are *among* the offered completions --
// other candidates (keywords like `badge_get`) may legitimately also appear
// at the same cursor position.
describe('reserved builtin completion (issue #326)', () => {
    const services = createTestServices();
    let parse: ReturnType<typeof createParse>;

    beforeAll(() => {
        parse = createParse();
    });

    async function completionLabelsAt(text: string, offset: number): Promise<string[]> {
        const document = await parse(text);
        const completions = await services.lsp.CompletionProvider?.getCompletion(
            document,
            textDocumentPositionParams(document, offset)
        );
        return (completions?.items ?? []).map(item => item.label);
    }

    test('offers all reserved int builtins inside an int expression', async () => {
        const stage = `
stage start {
    event enter {
        if () {
        }
    }
}
`;
        const text = `${VALID_GAME_BLOCK}${stage}`;
        const offset = text.indexOf('if (') + 'if ('.length;
        const labels = await completionLabelsAt(text, offset);

        for (const builtin of GQ_RESERVED_INTS) {
            expect(labels).toContain(builtin.name);
        }
        // Str builtins are not valid in an int expression position.
        expect(labels).not.toContain('GQS_LABEL1');
    });

    test('offers all reserved str builtins on the RHS of a str assignment', async () => {
        const stage = `
stage start {
    str greeting := "";
    event enter {
        greeting := ;
    }
}
`;
        const text = `${VALID_GAME_BLOCK}${stage}`;
        const offset = text.indexOf('greeting := ;') + 'greeting := '.length;
        const labels = await completionLabelsAt(text, offset);

        for (const builtin of GQ_RESERVED_STRS) {
            expect(labels).toContain(builtin.name);
        }
        // Int builtins are not valid in a str expression position.
        expect(labels).not.toContain('GQI_PLAYER_ID');
    });

    test('offers both int and str builtins as an assignment target', async () => {
        const stage = `
stage start {
    event enter {

    }
}
`;
        const text = `${VALID_GAME_BLOCK}${stage}`;
        // Cursor right after "enter {\n        " -- the start of a fresh
        // StageCommand, where both CmdAssignmentInt.dst and
        // CmdAssignmentStr.dst are viable next features.
        const offset = text.indexOf('event enter {') + 'event enter {\n'.length;
        const labels = await completionLabelsAt(text, offset);

        expect(labels).toContain('GQI_PLAYER_ID');
        expect(labels).toContain('GQS_LABEL1');
    });
});
