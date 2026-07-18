import { beforeAll, describe, expect, test } from 'vitest';
import { MarkupContent } from 'vscode-languageserver';
import { textDocumentPositionParams } from 'langium/test';
import { createParse, createTestServices, VALID_GAME_BLOCK } from './test-utils.js';

// Hover surfaces a builtin's description and writable/read-only status
// (gamequeer#326).
describe('reserved builtin hover (issue #326)', () => {
    const services = createTestServices();
    let parse: ReturnType<typeof createParse>;

    beforeAll(() => {
        parse = createParse();
    });

    async function hoverAt(text: string, offset: number): Promise<string | undefined> {
        const document = await parse(text);
        const hover = await services.lsp.HoverProvider?.getHoverContent(document, textDocumentPositionParams(document, offset));
        return hover && MarkupContent.is(hover.contents) ? hover.contents.value : undefined;
    }

    test('hovering a read-only int builtin shows its description and read-only status', async () => {
        const stage = `
stage start {
    event enter {
        if (GQI_PLAYER_ID == 1) {
        }
    }
}
`;
        const text = `${VALID_GAME_BLOCK}${stage}`;
        const offset = text.indexOf('GQI_PLAYER_ID') + 3;
        const content = await hoverAt(text, offset);

        expect(content).toContain('GQI_PLAYER_ID');
        expect(content).toContain('Player ID');
        expect(content).toContain('read-only');
    });

    test('hovering a writable str builtin shows its description and writable status', async () => {
        const stage = `
stage start {
    event enter {
        GQS_LABEL1 := "hi";
    }
}
`;
        const text = `${VALID_GAME_BLOCK}${stage}`;
        const offset = text.indexOf('GQS_LABEL1') + 3;
        const content = await hoverAt(text, offset);

        expect(content).toContain('GQS_LABEL1');
        expect(content).toContain('Label 1');
        expect(content).toContain('game-writable');
    });

    test('does not treat an unrelated identifier as a builtin', async () => {
        const stage = `
stage start {
    event enter {
        gostage start;
    }
}
`;
        const text = `${VALID_GAME_BLOCK}${stage}`;
        const offset = text.lastIndexOf('start;') + 2;
        const content = await hoverAt(text, offset);

        expect(content).toBeUndefined();
    });
});
