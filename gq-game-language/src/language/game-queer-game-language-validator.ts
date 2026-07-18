import type { ValidationAcceptor, ValidationChecks } from 'langium';
import type { CmdAssignmentInt, CmdAssignmentStr, GameAssignment, GameDefinitionSection, GameQueerGameLanguageAstType } from './generated/ast.js';
import type { GameQueerGameLanguageServices } from './game-queer-game-language-module.js';
import { findGqBuiltin } from './gq-builtins.js';

/**
 * Register custom validation checks.
 */
export function registerValidationChecks(services: GameQueerGameLanguageServices) {
    const registry = services.validation.ValidationRegistry;
    const validator = services.validation.GameQueerGameLanguageValidator;
    const checks: ValidationChecks<GameQueerGameLanguageAstType> = {
        GameDefinitionSection: validator.checkGameAssignmentCardinality,
        CmdAssignmentInt: validator.checkIntAssignmentBuiltin,
        CmdAssignmentStr: validator.checkStrAssignmentBuiltin
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

    /**
     * `dst = ...;` assigns with the int operator. If `dst` names a reserved
     * builtin, it must be an int builtin (a str builtin here is a kind
     * mismatch -- it needs `:=`), and if it's a read-only (VM/firmware-
     * managed) builtin, writing it is reported as a warning rather than an
     * error: the VM does not itself reject the write (see gamequeer#326),
     * so this is a lint, not a hard failure.
     */
    checkIntAssignmentBuiltin(node: CmdAssignmentInt, accept: ValidationAcceptor): void {
        const builtin = findGqBuiltin(node.dst);
        if (!builtin) {
            return;
        }
        if (builtin.kind !== 'int') {
            accept('error', `'${builtin.name}' is a str builtin; assign to it with ':=', not '='.`, { node, property: 'dst' });
            return;
        }
        if (!builtin.writable) {
            accept('warning', `'${builtin.name}' is a read-only builtin (${builtin.description}); the VM/firmware manages it and a game assignment will be overwritten.`, { node, property: 'dst' });
        }
    }

    /**
     * `dst := ...;` assigns with the str operator; see
     * {@link checkIntAssignmentBuiltin} for the mirrored int-side checks.
     */
    checkStrAssignmentBuiltin(node: CmdAssignmentStr, accept: ValidationAcceptor): void {
        const builtin = findGqBuiltin(node.dst);
        if (!builtin) {
            return;
        }
        if (builtin.kind !== 'str') {
            accept('error', `'${builtin.name}' is an int builtin; assign to it with '=', not ':='.`, { node, property: 'dst' });
            return;
        }
        if (!builtin.writable) {
            accept('warning', `'${builtin.name}' is a read-only builtin (${builtin.description}); the VM/firmware manages it and a game assignment will be overwritten.`, { node, property: 'dst' });
        }
    }
}
