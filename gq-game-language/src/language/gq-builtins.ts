/**
 * Reserved `GQI_*`/`GQS_*` builtin variables recognized by the gamequeer VM.
 *
 * Hand-synced from `gqc/src/gqc/structs.py` (`GQ_RESERVED_INTS` /
 * `GQ_RESERVED_STRS`) -- name/kind/description come from there. When those
 * tables change, update this file to match.
 *
 * `writable` is *not* present in `structs.py`; it was determined by reading
 * the VM (`gamequeer/src/gamequeer.c`, `gamequeer/src/menu.c`,
 * `gamequeer/src/bytecode.c`) and the firmware HAL (`ccs_workspace/qc2024/HAL_badge.c`)
 * to see who writes each variable, plus real usage in
 * `gamequeer/tests/golden/` and `examples/games/` (recursively). See the PR
 * description for the per-variable rationale.
 */

export type GqBuiltinKind = 'int' | 'str';

export interface GqBuiltin {
    /** e.g. `GQI_PLAYER_ID` */
    readonly name: string;
    readonly kind: GqBuiltinKind;
    /** From `structs.py`'s `GqReservedVariable.description`. */
    readonly description: string;
    /**
     * Whether game code may assign to this variable. `false` for VM/firmware
     * outputs (identity, menu results, cartridge metadata) that games only
     * ever read.
     */
    readonly writable: boolean;
}

export const GQ_RESERVED_INTS: readonly GqBuiltin[] = [
    { name: 'GQI_GAME_ID', kind: 'int', description: 'ID of the game', writable: false },
    { name: 'GQI_MENU_ACTIVE', kind: 'int', description: 'Menu active', writable: false },
    { name: 'GQI_MENU_VALUE', kind: 'int', description: 'Menu selection', writable: false },
    { name: 'GQI_GAME_COLOR', kind: 'int', description: 'Color of the game cartridge', writable: false },
    { name: 'GQI_BGANIM_X', kind: 'int', description: 'Background animation X', writable: true },
    { name: 'GQI_BGANIM_Y', kind: 'int', description: 'Background animation Y', writable: true },
    { name: 'GQI_FGANIM1_X', kind: 'int', description: 'Foreground animation 0 X', writable: true },
    { name: 'GQI_FGANIM1_Y', kind: 'int', description: 'Foreground animation 0 Y', writable: true },
    { name: 'GQI_FGMASK1_X', kind: 'int', description: 'Foreground mask 0 X', writable: true },
    { name: 'GQI_FGMASK1_Y', kind: 'int', description: 'Foreground mask 0 Y', writable: true },
    { name: 'GQI_FGANIM2_X', kind: 'int', description: 'Foreground animation 1 X', writable: true },
    { name: 'GQI_FGANIM2_Y', kind: 'int', description: 'Foreground animation 1 Y', writable: true },
    { name: 'GQI_FGMASK2_X', kind: 'int', description: 'Foreground mask 1 X', writable: true },
    { name: 'GQI_FGMASK2_Y', kind: 'int', description: 'Foreground mask 1 Y', writable: true },
    { name: 'GQI_LABEL1_X', kind: 'int', description: 'Label 1 X', writable: true },
    { name: 'GQI_LABEL1_Y', kind: 'int', description: 'Label 1 Y', writable: true },
    { name: 'GQI_LABEL2_X', kind: 'int', description: 'Label 2 X', writable: true },
    { name: 'GQI_LABEL2_Y', kind: 'int', description: 'Label 2 Y', writable: true },
    { name: 'GQI_LABEL3_X', kind: 'int', description: 'Label 3 X', writable: true },
    { name: 'GQI_LABEL3_Y', kind: 'int', description: 'Label 3 Y', writable: true },
    { name: 'GQI_LABEL4_X', kind: 'int', description: 'Label 4 X', writable: true },
    { name: 'GQI_LABEL4_Y', kind: 'int', description: 'Label 4 Y', writable: true },
    { name: 'GQI_LABEL_FLAGS', kind: 'int', description: 'Label flags', writable: true },
    { name: 'GQI_PLAYER_ID', kind: 'int', description: 'Player ID', writable: false }
];

export const GQ_RESERVED_STRS: readonly GqBuiltin[] = [
    { name: 'GQS_GAME_NAME', kind: 'str', description: 'Name of the game', writable: false },
    { name: 'GQS_PLAYER_HANDLE', kind: 'str', description: 'Player handle', writable: true },
    { name: 'GQS_LABEL1', kind: 'str', description: 'Label 1', writable: true },
    { name: 'GQS_LABEL2', kind: 'str', description: 'Label 2', writable: true },
    { name: 'GQS_LABEL3', kind: 'str', description: 'Label 3', writable: true },
    { name: 'GQS_LABEL4', kind: 'str', description: 'Label 4', writable: true },
    { name: 'GQS_TEXTMENU_RESULT', kind: 'str', description: 'Text menu result', writable: true }
];

export const GQ_RESERVED_BUILTINS: readonly GqBuiltin[] = [...GQ_RESERVED_INTS, ...GQ_RESERVED_STRS];

export const GQ_RESERVED_BUILTINS_BY_NAME: ReadonlyMap<string, GqBuiltin> = new Map(
    GQ_RESERVED_BUILTINS.map(builtin => [builtin.name, builtin])
);

export function findGqBuiltin(name: string): GqBuiltin | undefined {
    return GQ_RESERVED_BUILTINS_BY_NAME.get(name);
}

/** Markdown hover text for a builtin: description plus read-only/writable status. */
export function gqBuiltinHoverMarkdown(builtin: GqBuiltin): string {
    const status = builtin.writable ? 'game-writable' : 'read-only (VM/firmware-managed)';
    return `**${builtin.name}** _(${builtin.kind} builtin, ${status})_\n\n${builtin.description}`;
}

/** One-line completion-item detail: description plus read-only/writable status. */
export function gqBuiltinCompletionDetail(builtin: GqBuiltin): string {
    const status = builtin.writable ? 'writable' : 'read-only';
    return `${builtin.kind} builtin (${status}) -- ${builtin.description}`;
}
