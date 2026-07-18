import { beforeAll, describe, expect, test } from 'vitest';
import { createParse, lexerAndParserErrors, VALID_GAME_BLOCK } from './test-utils.js';

// Regression coverage for the terminal INPUTBUTTON -> plain-keyword change
// (issue #321, fix 2): '<-', '->', and '-' are now bare keywords reused by
// event_input_button, so this proves they still coexist correctly with the
// same tokens used elsewhere in the grammar (arithmetic '-', comparison
// operators, and the file-binding '<-' arrow) rather than being shadowed or
// mis-lexed.

let parse: ReturnType<typeof createParse>;

beforeAll(() => {
    parse = createParse();
});

describe('INPUTBUTTON keyword coexistence with other operators (issue #321, fix 2 regression)', () => {
    test('binary arithmetic minus still parses', async () => {
        const document = await parse(`
${VALID_GAME_BLOCK}
stage start {
    event enter {
        x = a - 1;
    }
}
`);
        expect(lexerAndParserErrors(document)).toEqual([]);
    });

    test('unary minus still parses', async () => {
        const document = await parse(`
${VALID_GAME_BLOCK}
stage start {
    event enter {
        x = -a;
    }
}
`);
        expect(lexerAndParserErrors(document)).toEqual([]);
    });

    test('the "<" comparison operator still parses', async () => {
        const document = await parse(`
${VALID_GAME_BLOCK}
stage start {
    event enter {
        if (a < b) {
            gostage start;
        }
    }
}
`);
        expect(lexerAndParserErrors(document)).toEqual([]);
    });

    test('the "<=" comparison operator still parses', async () => {
        const document = await parse(`
${VALID_GAME_BLOCK}
stage start {
    event enter {
        if (a <= b) {
            gostage start;
        }
    }
}
`);
        expect(lexerAndParserErrors(document)).toEqual([]);
    });

    test('the "<-" file-binding arrow still works alongside an event input(<-) handler in the same program', async () => {
        const document = await parse(`
${VALID_GAME_BLOCK}
animations {
    hearts <- "heart_anim.gif";
}
stage start {
    event input(<-) {
        gostage start;
    }
}
`);
        expect(lexerAndParserErrors(document)).toEqual([]);
    });
});
