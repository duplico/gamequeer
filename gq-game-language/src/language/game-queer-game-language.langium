grammar GameQueerGameLanguage

hidden terminal WS: /\s+/;
terminal ID: /[_a-zA-Z][\w_]*/;
terminal INT returns number: /\-?[0-9]+/;

terminal STRING: /"(\\.|[^"\\])*"/;

terminal INPUTBUTTON: '(A)' | '(B)' | '(<-)' | '(->)';

hidden terminal ML_COMMENT: /\/\*[\s\S]*?\*\//;
hidden terminal SL_COMMENT: /\/\/[^\n\r]*/;

entry Program:
   GameDefinitionSection dec=DeclarationSection*;

DeclarationSection:
    VarDefinitionSection | AnimationDefinitionSection | LightcueDefinitionSection | MenuDefinitionSection | StageDefinition;

// Game definition section
GameIdAssignment:
    'id' '=' id=INT ';';
GameTitleAssignment:
    'title' ':=' title=STRING ';';
GameAuthorAssignment:
    'author' ':=' title=STRING ';';
GameStartingStageAssignment:
    'starting_stage' '=' stage=ID ';';
GameAssignment:
    GameIdAssignment | GameTitleAssignment | GameAuthorAssignment | GameStartingStageAssignment;
GameDefinitionSection:
    'game' '{' games=GameAssignment* '}';

// Variable definition section
IntDefinition: 
    'int' name=ID '=' value=INT ';';
StrDefinition: 
    'str' name=ID ':=' value=STRING ';';
VarDefinition: 
    IntDefinition| StrDefinition;
VarDefinitionSection:
    storageclass=('volatile' | 'persistent') (VarDefinition | '{' vars=VarDefinition* '}');

// File assignment shared by lightcues and animations
FileAssignment:
    name=ID '<-' src=STRING;

// Animation definition section
AnimationOption: 
    'frame_rate' '=' framerate=INT ';' | 'dithering' ':=' dithering=STRING ';';
AnimationAssignment:
    FileAssignment (AnimationOption? ';' | '{' anim_options=AnimationOption* '}');
AnimationDefinitionSection:
    'animations' (AnimationAssignment | '{' anims=AnimationAssignment* '}');

// Lightcue definition section
LightcueDefinitionSection:
    'lightcues' (file=FileAssignment ';' | '{' (file=FileAssignment ';')* '}');

// Menu definition section
MenuOption:
    returnValue=INT ':' label=STRING ';';
MenuDefinition:
    name=ID (MenuOption | '{' options=MenuOption* '}');
MenuDefinitionSection:
    'menus' (MenuDefinition | '{' menus=MenuDefinition* '}');

// Stage commands
CmdGoStage:
    'gostage' stage=ID ';';
CmdPlayBgAnim:
    'play' 'bganim' anim=ID ';';
CmdPlayCue:
    'cue' cue=ID ';';

IntOperand:
    var=ID | val=INT;
IntOperator:
    operator=('+' | '-' | '*' | '/' | '%' | '&&' | '||' | '==' | '!=' | '<' | '>' | '<=' | '>=');
IntExprParen:
    '(' expr=IntExpr ')';
IntUnaryExpr:
    operator=('!' | '-') operand=IntExpr;
IntExpr:
    IntOperand | IntOperand IntOperator IntExpr | IntExprParen | IntUnaryExpr;

CmdAssignmentInt:
    dst=ID '=' src=IntExpr ';';
CmdAssignmentStr:
    dst=ID ':=' src=ID ';';

CmdAssignment:
    CmdAssignmentInt | CmdAssignmentStr;

StageCommand:
    CmdGoStage | CmdPlayBgAnim | CmdPlayCue | CmdAssignment;

// Stage definitions

EventType:
    eventType='input' button=INPUTBUTTON | eventType='bgdone' | eventType='menu' | eventType='enter';
StageEvent:
    'event' EventType (StageCommand | '{' cmds=StageCommand* '}');
StageMenu:
    'menu' menu=ID ('prompt' prompt=STRING)? ';';
StageBgAnim:
    'bganim' anim=ID ';';
StageBgCue:
    'bgcue' cue=ID ';';

StageOption:
    StageEvent | StageMenu | StageBgAnim | StageBgCue;

StageDefinition:
    'stage' name=ID (StageOption | '{' stage_opts=StageOption* '}');

