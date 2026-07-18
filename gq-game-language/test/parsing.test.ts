import { beforeAll, describe, expect, test } from 'vitest';
import { createParse, lexerAndParserErrors, VALID_GAME_BLOCK } from './test-utils.js';

let parse: ReturnType<typeof createParse>;

beforeAll(() => {
    parse = createParse();
});

describe('AnimationAssignment single-inline-option form (issue #321, fix 1)', () => {
    test('accepts a single inline option terminated by exactly one semicolon', async () => {
        const document = await parse(`
${VALID_GAME_BLOCK}
animations {
    sprite <- "x.gif" frame_rate = 4;
}
stage start {
}
`);
        expect(lexerAndParserErrors(document)).toEqual([]);
    });

    test('still accepts a bare file assignment with no options', async () => {
        const document = await parse(`
${VALID_GAME_BLOCK}
animations {
    sprite <- "x.gif";
}
stage start {
}
`);
        expect(lexerAndParserErrors(document)).toEqual([]);
    });

    test('still accepts a braced multi-option form', async () => {
        const document = await parse(`
${VALID_GAME_BLOCK}
animations {
    sprite <- "x.gif" {
        frame_rate = 4;
        dithering := "sierra2_4a";
    }
}
stage start {
}
`);
        expect(lexerAndParserErrors(document)).toEqual([]);
    });

    test('rejects a trailing semicolon after an inline option (that was never valid)', async () => {
        const document = await parse(`
${VALID_GAME_BLOCK}
animations {
    sprite <- "x.gif" frame_rate = 4;;
}
stage start {
}
`);
        expect(lexerAndParserErrors(document)).not.toEqual([]);
    });
});

describe('input(...) event type with inner whitespace (issue #321, fix 2)', () => {
    test('accepts spaced-out parens and button', async () => {
        const document = await parse(`
${VALID_GAME_BLOCK}
stage start {
    event input ( A ) {
        gostage start;
    }
}
`);
        expect(lexerAndParserErrors(document)).toEqual([]);
    });

    test('still accepts the tight form', async () => {
        const document = await parse(`
${VALID_GAME_BLOCK}
stage start {
    event input(A) {
        gostage start;
    }
}
`);
        expect(lexerAndParserErrors(document)).toEqual([]);
    });

    test.each(['A', 'B', '<-', '->', '-'])('accepts button %s', async (button) => {
        const document = await parse(`
${VALID_GAME_BLOCK}
stage start {
    event input( ${button} ) {
        gostage start;
    }
}
`);
        expect(lexerAndParserErrors(document)).toEqual([]);
    });
});
