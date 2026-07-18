import { EmptyFileSystem, type LangiumDocument } from 'langium';
import { parseHelper } from 'langium/test';
import { createGameQueerGameLanguageServices } from '../src/language/game-queer-game-language-module.js';
import type { Program } from '../src/language/generated/ast.js';

export function createTestServices() {
    return createGameQueerGameLanguageServices(EmptyFileSystem).GameQueerGameLanguage;
}

export function createParse() {
    return parseHelper<Program>(createTestServices());
}

/** A minimal, well-formed `game { ... }` block: exactly one of each required key. */
export const VALID_GAME_BLOCK = `
game {
    id = 0;
    title := "Test Game";
    author := "duplico";
    starting_stage = start;
}
`;

export function lexerAndParserErrors(document: LangiumDocument<Program>): string[] {
    return [
        ...document.parseResult.lexerErrors.map(e => `lexer: ${e.message}`),
        ...document.parseResult.parserErrors.map(e => `parser: ${e.message}`)
    ];
}
