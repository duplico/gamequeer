import type { ValidationAcceptor, ValidationChecks } from 'langium';
import type { GameAssignment, GameDefinitionSection, GameQueerGameLanguageAstType } from './generated/ast.js';
import type { GameQueerGameLanguageServices } from './game-queer-game-language-module.js';

/**
 * Register custom validation checks.
 */
export function registerValidationChecks(services: GameQueerGameLanguageServices) {
    const registry = services.validation.ValidationRegistry;
    const validator = services.validation.GameQueerGameLanguageValidator;
    const checks: ValidationChecks<GameQueerGameLanguageAstType> = {
        GameDefinitionSection: validator.checkGameAssignmentCardinality
    };
    registry.register(checks, validator);
}

// Maps each GameAssignment alternative to the game-block key it assigns.
const GAME_ASSIGNMENT_KEYS: Record<GameAssignment['$type'], string> = {
    GameIdAssignment: 'id',
    GameTitleAssignment: 'title',
    GameAuthorAssignment: 'author',
    GameStartingStageAssignment: 'starting_stage'
};

/**
 * Implementation of custom validations.
 */
export class GameQueerGameLanguageValidator {

    /**
     * gqc requires the `game { ... }` block to contain exactly one of each of
     * `id`, `title`, `author`, and `starting_stage`, in any order (grammar.py,
     * `pp.Each`). The grammar itself stays permissive here -- Langium can't
     * express "unordered, exactly once" -- so this check reports missing and
     * duplicate keys instead.
     */
    checkGameAssignmentCardinality(section: GameDefinitionSection, accept: ValidationAcceptor): void {
        const assignmentsByKey = new Map<string, GameAssignment[]>();
        for (const key of Object.values(GAME_ASSIGNMENT_KEYS)) {
            assignmentsByKey.set(key, []);
        }
        for (const assignment of section.games) {
            assignmentsByKey.get(GAME_ASSIGNMENT_KEYS[assignment.$type])!.push(assignment);
        }

        for (const [key, assignments] of assignmentsByKey) {
            if (assignments.length === 0) {
                accept('error', `Game block is missing required assignment '${key}'.`, { node: section, property: 'games' });
            } else if (assignments.length > 1) {
                for (const duplicate of assignments.slice(1)) {
                    accept('error', `Duplicate '${key}' assignment in game block; exactly one is allowed.`, { node: duplicate });
                }
            }
        }
    }
}
