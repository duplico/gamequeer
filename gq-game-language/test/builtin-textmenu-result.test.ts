import { beforeAll, describe, expect, test } from 'vitest';
import { createParse, lexerAndParserErrors, VALID_GAME_BLOCK } from './test-utils.js';

// Targeted repro of GQS_TEXTMENU_RESULT's pre-seed-before-textmenu write
// pattern from gqc/examples/skel/games/working_samples/sample_working_simple.gq
// (lines 191-196 as of gamequeer#328):
//
//   event enter {
//       GQS_TEXTMENU_RESULT := my_name;
//   }
//   event menu {
//       my_name := GQS_TEXTMENU_RESULT;
//   }
//
// This is the evidence that GQS_TEXTMENU_RESULT is writable (not read-only,
// as the issue speculated): the game assigns it to pre-seed the text-entry
// buffer, and menu.c's menu_text_load() explicitly documents honoring that
// pre-set value. That source file itself isn't swept by golden.test.ts --
// two of its sibling fixtures hit an unrelated grammar issue
// (gamequeer#340) that would otherwise mask this assertion -- so this test
// parses the relevant snippet directly instead.
describe('GQS_TEXTMENU_RESULT pre-seed pattern (issue #326)', () => {
    let parse: ReturnType<typeof createParse>;

    beforeAll(() => {
        parse = createParse();
    });

    test('pre-seeding and reading back GQS_TEXTMENU_RESULT produces no diagnostics', async () => {
        const declAndStage = `
volatile {
    str my_name := "Name";
}
stage start {
    event enter {
        GQS_TEXTMENU_RESULT := my_name;
    }

    event menu {
        my_name := GQS_TEXTMENU_RESULT;
    }
}
`;
        const document = await parse(`${VALID_GAME_BLOCK}${declAndStage}`, { validation: true });

        expect(lexerAndParserErrors(document)).toEqual([]);
        expect(document.diagnostics ?? []).toEqual([]);
    });
});
