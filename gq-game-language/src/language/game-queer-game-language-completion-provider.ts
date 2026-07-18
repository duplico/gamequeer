import { AstUtils, GrammarAST, type MaybePromise } from 'langium';
import { DefaultCompletionProvider, type CompletionAcceptor, type CompletionContext, type NextFeature } from 'langium/lsp';
import { CompletionItemKind } from 'vscode-languageserver';
import { GQ_RESERVED_INTS, GQ_RESERVED_STRS, gqBuiltinCompletionDetail, type GqBuiltin } from './gq-builtins.js';

// Parser rules whose `var=ID`/`dst=ID` assignment accepts a reserved
// GQI_*/GQS_* builtin name as well as a user-defined variable: int
// operands/assignment targets, and str operands/assignment targets. The
// grammar captures these as plain strings (not cross-references -- see
// issue #326), so the default CompletionProvider has no completions for
// them at all; this override adds the builtin table alongside whatever else
// ends up being offered for that position.
const INT_IDENTIFIER_RULES = new Set(['IntOperand', 'CmdAssignmentInt']);
const STR_IDENTIFIER_RULES = new Set(['StrOperand', 'CmdAssignmentStr']);

/**
 * Contributes the reserved `GQI_*`/`GQS_*` builtins to completion in
 * identifier positions of int/str expressions and assignment left-hand
 * sides (gamequeer#326).
 */
export class GameQueerGameLanguageCompletionProvider extends DefaultCompletionProvider {

    protected override completionFor(context: CompletionContext, next: NextFeature, acceptor: CompletionAcceptor): MaybePromise<void> {
        const builtins = this.builtinsFor(next);
        if (builtins) {
            for (const builtin of builtins) {
                acceptor(context, {
                    label: builtin.name,
                    kind: CompletionItemKind.Variable,
                    detail: gqBuiltinCompletionDetail(builtin),
                    sortText: '0'
                });
            }
        }
        return super.completionFor(context, next, acceptor);
    }

    private builtinsFor(next: NextFeature): readonly GqBuiltin[] | undefined {
        // The completion feature stack surfaces the *terminal* being
        // completed (here, a RuleCall to the `ID` terminal), not the
        // wrapping Assignment -- so we look at `$container` to find out
        // which property (`var`/`dst`) it's assigned to.
        const assignment = next.feature.$container;
        if (!GrammarAST.isAssignment(assignment)) {
            return undefined;
        }
        if (assignment.feature !== 'var' && assignment.feature !== 'dst') {
            return undefined;
        }
        const rule = AstUtils.getContainerOfType(assignment, GrammarAST.isParserRule);
        if (!rule) {
            return undefined;
        }
        if (INT_IDENTIFIER_RULES.has(rule.name)) {
            return GQ_RESERVED_INTS;
        }
        if (STR_IDENTIFIER_RULES.has(rule.name)) {
            return GQ_RESERVED_STRS;
        }
        return undefined;
    }
}
