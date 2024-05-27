import type { ValidationChecks } from 'langium';
import type { GameQueerGameLanguageAstType } from './generated/ast.js';
import type { GameQueerGameLanguageServices } from './game-queer-game-language-module.js';

/**
 * Register custom validation checks.
 */
export function registerValidationChecks(services: GameQueerGameLanguageServices) {
    const registry = services.validation.ValidationRegistry;
    const validator = services.validation.GameQueerGameLanguageValidator;
    const checks: ValidationChecks<GameQueerGameLanguageAstType> = {
    };
    registry.register(checks, validator);
}

/**
 * Implementation of custom validations.
 */
export class GameQueerGameLanguageValidator {

}
