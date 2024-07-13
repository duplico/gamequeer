import struct

from . import structs
from .structs import OpCode as CommandType
from .datamodel import Stage, Animation, LightCue, Variable, GqcIntOperand

class Command:
    command_list = []

    def __init__(self, command_type : CommandType, instring = None, loc = None,  flags : int = 0, arg1 : int = 0, arg2 : int = 0):
        self.instring = instring
        self.loc = loc
        self.addr = 0x00000000 # TODO
        
        self.command_type = command_type
        self.command_flags = flags
        self.arg1 = arg1
        self.arg2 = arg2
        self.resolved = False

        Command.command_list.append(self)
    
    def resolve(self):
        # TODO: Probably not this:
        self.resolved = True
        return True
    
    def set_addr(self, addr : int, namespace : int = structs.GQ_PTR_NS_CART):
        # TODO: Add a check to ensure that the namespace byte isn't already
        #       set in the address.
        self.addr = structs.gq_ptr_apply_ns(namespace, addr)

    def to_bytes(self):
        if not self.resolve():
            # TODO: Raise a GqError here, or otherwise show the location of the error in source
            raise ValueError("Unresolved command symbols remain")

        op = structs.GqOp(
            opcode=self.command_type,
            flags=self.command_flags,
            arg1=self.arg1,
            arg2=self.arg2
        )
        return struct.pack(structs.GQ_OP_FORMAT, *op)
    
    def size(self):
        return structs.GQ_OP_SIZE

    def __repr__(self) -> str:
        return f"Command({self.command_type.name}:{self.command_flags} {self.arg1} {self.arg2});"

class CommandDone(Command):
    def __init__(self):
        super().__init__(CommandType.DONE)
        self.resolved = True

    def __repr__(self) -> str:
        return "DONE"

class CommandGoStage(Command):
    def __init__(self, instring, loc, stage : str):
        super().__init__(CommandType.GOSTAGE, instring, loc)
        self.stage_name = stage
    
    def resolve(self):
        if self.resolved:
            return True

        # TODO: Extract constant for NULL:
        if self.stage_name in Stage.stage_table and Stage.stage_table[self.stage_name].addr != 0x00000000:
            self.arg1 = Stage.stage_table[self.stage_name].addr
            self.resolved = True
        
        return self.resolved

    def __repr__(self) -> str:
        return f"GOSTAGE {self.arg1}"

class CommandPlayBg(Command):
    def __init__(self, instring, loc, bganim : str):
        super().__init__(CommandType.PLAYBG, instring, loc)
        self.anim_name = bganim
    
    def resolve(self):
        if self.resolved:
            return True

        if self.anim_name in Animation.anim_table and Animation.anim_table[self.anim_name].addr != 0x00000000:
            self.arg1 = Animation.anim_table[self.anim_name].addr
            self.resolved = True
        
        return self.resolved
    
    def __repr__(self) -> str:
        return f"PLAYBG {self.arg1}"

class CommandCue(Command):
    def __init__(self, instring, loc, cue : str):
        super().__init__(CommandType.CUE, instring, loc)
        self.cue_name = cue
    
    def resolve(self):
        if self.resolved:
            return True

        if self.cue_name in LightCue.cue_table and LightCue.cue_table[self.cue_name].addr != 0x00000000:
            self.arg1 = LightCue.cue_table[self.cue_name].addr
            self.resolved = True
        
        return self.resolved
    
    def __repr__(self) -> str:
        return f"CUE {self.arg1}"

class CommandArithmetic(Command):
    def __init__(self, command_type : CommandType, instring, loc, dst : GqcIntOperand, src : GqcIntOperand):
        if command_type not in [CommandType.ADDBY, CommandType.SUBBY, CommandType.MULBY, CommandType.DIVBY, CommandType.MODBY]:
            raise ValueError(f"Invalid arithmetic command {command_type}")

        super().__init__(command_type, instring, loc)

        if dst.is_literal:
            # TODO: decode the code location.
            raise ValueError("Unmodifiable lvalue!")
        self.dst_name = dst.value
        self.src = src
        
        self.resolve()
    
    def resolve(self):
        if self.resolved:
            return True

        resolved = True

        # dst is guaranteed not to be a literal, so:
        if self.dst_name in Variable.var_table and Variable.var_table[self.dst_name].addr != 0x00000000:
            self.arg1 = Variable.var_table[self.dst_name].addr
        else:
            resolved = False
        
        if self.src.is_literal:
            self.arg2 = self.src.value
            self.command_flags |= structs.OpFlags.LITERAL_ARG2
        elif self.src.value in Variable.var_table and Variable.var_table[self.src.value].addr != 0x00000000:
            self.arg2 = Variable.var_table[self.src.value].addr
        else:
            resolved = False
        
        self.resolved = resolved
        
        return self.resolved

# TODO: crib from the above, and create separate SetVar for int and strings with different namedstructs
class CommandSetVar(Command):
    def __init__(self, instring, loc, datatype : str, dst : str, src = None, src_is_literal = False, src_is_expression = False):
        super().__init__(CommandType.SETVAR, instring, loc, arg1=None, arg2=None)
        self.dst_name = dst
        self.datatype = datatype

        self.src_is_literal = src_is_literal
        self.src_is_expression = src_is_expression

        if src_is_literal and datatype == 'int':
            self.command_flags |= structs.OpFlags.LITERAL_ARG2
            self.arg2 = src
        elif src_is_literal and datatype == 'str':
            # TODO: create a value for it in .init
            raise NotImplementedError("Cannot set a string variable to a literal")
        elif src_is_expression and datatype == 'int':
            self.src_expr = src
        elif src_is_expression and datatype == 'str':
            raise NotImplementedError("Cannot set a string variable to an expression")
        else:
            self.src_name = src

        if self.datatype == "str":
            self.command_flags |= structs.OpFlags.TYPE_STR
        elif self.datatype == "int":
            self.command_flags |= structs.OpFlags.TYPE_INT
        else:
            raise ValueError(f"Invalid datatype {self.datatype}")

        self.resolve()
    
    def resolve(self):
        if self.resolved:
            return True

        resolved = True

        # TODO: Test for null differently:
        # TODO: Test for valid memory namespaces:
        if self.dst_name in Variable.var_table and Variable.var_table[self.dst_name].addr != 0x00000000:
            self.arg1 = Variable.var_table[self.dst_name].addr
        else:
            resolved = False
        
        if self.src_is_expression:
            if not self.src_expr.resolve():
                resolved = False
                return False
            else:
                # TODO: confirm this can never be a literal
                self.src_name = self.src_expr.result_symbol.value
                # TODO: take expression generated code and prepend it to my code

        if not self.src_is_literal:
            if self.src_name in Variable.var_table and Variable.var_table[self.src_name].addr != 0x00000000:
                self.arg2 = Variable.var_table[self.src_name].addr
            else:
                resolved = False
        
        # Rudimentary type checking:
        if not self.src_is_literal and self.src_name in Variable.var_table:
            if Variable.var_table[self.src_name].datatype != self.datatype:
                raise ValueError(f"Variable {self.src_name} is of type {Variable.var_table[self.src_name].datatype}, not {self.datatype}")
        if self.dst_name in Variable.var_table:
            if Variable.var_table[self.dst_name].datatype != self.datatype:
                raise ValueError(f"Variable {self.dst_name} is of type {Variable.var_table[self.dst_name].datatype}, not {self.datatype}")

        self.resolved = resolved
        
        return self.resolved
    
    def to_bytes(self):
        if self.src_is_expression:
            expression_cmd_bytes = b''
            for cmd in self.src_expr.commands:
                if not cmd.resolve():
                    raise ValueError("Unresolved symbol in expression")
                expression_cmd_bytes += cmd.to_bytes()
            return expression_cmd_bytes + super().to_bytes()
        else:
            return super().to_bytes()

    def size(self):
        if self.src_is_expression:
            size = 0
            for cmd in self.src_expr.commands:
                size += cmd.size()
            return size + super().size()
        else:
            return super().size()

    def __repr__(self) -> str:
        return f"SETVAR {self.dst_name} {self.arg2 if self.src_is_literal else self.src_name}"

class CommandGoto(Command):
    def __init__(self, instring, loc, addr : int = 0x00000000):
        super().__init__(CommandType.GOTO, instring, loc)
        self.arg1 = addr
    
    def resolve(self):
        if self.resolved:
            return True
        
        if self.arg1 != 0x00000000:
            self.resolved = True
        
        return self.resolved
    
    def __repr__(self) -> str:
        return f"GOTO {self.arg1}"
