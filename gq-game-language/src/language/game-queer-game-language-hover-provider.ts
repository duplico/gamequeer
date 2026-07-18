import type { LangiumDocument, MaybePromise } from 'langium';
import { CstUtils } from 'langium';
import { MultilineCommentHoverProvider } from 'langium/lsp';
import type { Hover, HoverParams } from 'vscode-languageserver';
import { isCmdAssignmentInt, isCmdAssignmentStr, isIntOperand, isStrOperand } from './generated/ast.js';
import { findGqBuiltin, gqBuiltinHoverMarkdown } from './gq-builtins.js';

/**
 * Surfaces the description (and read-only/writable status) of a reserved
 * `GQI_*`/`GQS_*` builtin on hover (gamequeer#326). Falls back to the
 * default declaration-based hover for everything else.
 */
export class GameQueerGameLanguageHoverProvider extends MultilineCommentHoverProvider {

    override getHoverContent(document: LangiumDocument, params: HoverParams): MaybePromise<Hover | undefined> {
        const builtinHover = this.getBuiltinHoverContent(document, params);
        if (builtinHover) {
            return builtinHover;
        }
        return super.getHoverContent(document, params);
    }

    private getBuiltinHoverContent(document: LangiumDocument, params: HoverParams): Hover | undefined {
        const rootNode = document.parseResult?.value?.$cstNode;
        if (!rootNode) {
            return undefined;
        }
        const offset = document.textDocument.offsetAt(params.position);
        const cstNode = CstUtils.findDeclarationNodeAtOffset(rootNode, offset, this.grammarConfig.nameRegexp);
        if (!cstNode || cstNode.offset + cstNode.length <= offset) {
            return undefined;
        }

        const astNode = cstNode.astNode;
        const text = cstNode.text;
        const isBuiltinIdentifierSlot =
            (isIntOperand(astNode) && astNode.var === text) ||
            (isStrOperand(astNode) && astNode.var === text) ||
            (isCmdAssignmentInt(astNode) && astNode.dst === text) ||
            (isCmdAssignmentStr(astNode) && astNode.dst === text);
        if (!isBuiltinIdentifierSlot) {
            return undefined;
        }

        const builtin = findGqBuiltin(text);
        if (!builtin) {
            return undefined;
        }
        return {
            contents: {
                kind: 'markdown',
                value: gqBuiltinHoverMarkdown(builtin)
            }
        };
    }
}
