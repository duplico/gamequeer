import struct

from gqc.structs import GQ_PTR_NS_CART

from . import structs
from .structs import OpCode as CommandType
from .datamodel import Stage, Animation, LightCue, Variable, GqcIntOperand, IntExpression

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
        
        if self.command_flags & structs.OpFlags.LITERAL_ARG2 and self.command_flags & structs.OpFlags.LITERAL_ARG1:
            return struct.pack(structs.GQ_OP_FORMAT_LITERAL_ARGS, *op)
        elif self.command_flags & structs.OpFlags.LITERAL_ARG1:
            return struct.pack(structs.GQ_OP_FORMAT_LITERAL_ARG1, *op)
        elif self.command_flags & structs.OpFlags.LITERAL_ARG2:
            return struct.pack(structs.GQ_OP_FORMAT_LITERAL_ARG2, *op)

        return struct.pack(structs.GQ_OP_FORMAT, *op)
    
    def size(self):
        return structs.GQ_OP_SIZE

    def __repr__(self) -> str:
        return f"Command({self.command_type.name}:{self.command_flags:#0{4}x} {self.arg1:#0{10}x} {self.arg2:#0{10}x});"

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
    OPERATORS = {
        '+': CommandType.ADDBY,
        '-': CommandType.SUBBY,
        '*': CommandType.MULBY,
        '/': CommandType.DIVBY,
        '%': CommandType.MODBY,
        '==': CommandType.EQ,
        '!=': CommandType.NE,
        '>': CommandType.GT,
        '<': CommandType.LT,
        '>=': CommandType.GE,
        '<=': CommandType.LE,
        '&&': CommandType.AND,
        '||': CommandType.OR,
    }

    UNARY_OPERATORS = {
        '!': CommandType.NOT,
        '-': CommandType.NEG
    }

    def __init__(self, command_type : CommandType, instring, loc, dst : GqcIntOperand, src : GqcIntOperand):
        if command_type not in CommandArithmetic.OPERATORS.values() and command_type not in CommandArithmetic.UNARY_OPERATORS.values():
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

class CommandSetStr(Command):
    def __init__(self, instring, loc, dst : str, src = None):
        super().__init__(CommandType.SETVAR, instring, loc, arg1=None, arg2=None)
        self.dst_name = dst
        self.src_name = src
        self.command_flags |= structs.OpFlags.TYPE_STR

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

        if self.src_name in Variable.var_table and Variable.var_table[self.src_name].addr != 0x00000000:
            self.arg2 = Variable.var_table[self.src_name].addr
        else:
            resolved = False
        
        # Rudimentary type checking:
        if self.src_name in Variable.var_table:
            if Variable.var_table[self.src_name].datatype != 'str':
                raise ValueError(f"Variable {self.src_name} is of type {Variable.var_table[self.src_name].datatype}, not str")
        if self.dst_name in Variable.var_table:
            if Variable.var_table[self.dst_name].datatype != 'str':
                raise ValueError(f"Variable {self.dst_name} is of type {Variable.var_table[self.dst_name].datatype}, not str")

        self.resolved = resolved
        return self.resolved

    def __repr__(self) -> str:
        return f"SETSTR {self.dst_name} {self.src_name}"

class CommandGoto(Command):
    def __init__(self, instring, loc, addr : int = 0x00000000, form : str = None):
        super().__init__(CommandType.GOTO, instring, loc)
        self.arg1 = addr
        self.form = form
    
    def resolve(self):
        if self.resolved:
            return True
        
        if self.arg1 != 0x00000000:
            self.resolved = True
        
        return self.resolved
    
    def __repr__(self) -> str:
        return f"GOTO {self.arg1:#0{10}x}"

class CommandWithIntExpressionArgument(Command):
    # TODO: Maybe track whether the expression is arg1 or arg2 or both?
    #       But, for now, it'll be assumed that the expression is arg2.
    def __init__(self, command_type : CommandType, instring, loc, expr_or_operand : GqcIntOperand | IntExpression):
        super().__init__(command_type, instring, loc)

        self.arg2_is_expression = isinstance(expr_or_operand, IntExpression)
        self.arg2_section_size = 0
        self.expr_or_operand = expr_or_operand

        if self.arg2_is_expression:
            self.arg2_name = self.expr_or_operand.result_symbol.value
            self.arg2_section_size = self.expr_or_operand.size()
        elif expr_or_operand.is_literal:
            self.command_flags |= structs.OpFlags.LITERAL_ARG2
            self.arg2 = expr_or_operand.value
        else:
            self.arg2_name = expr_or_operand.value
        
        self.resolve()
    
    def resolve(self):
        if self.resolved:
            return True

        resolved = True

        if self.arg2_is_expression and not self.expr_or_operand.resolve():
            resolved = False
            return False
        
        # If the expression is a literal, it was already resolved in __init__.
        # If the expression is a reference, attempt to resolve the reference:
        if self.arg2_is_expression or not self.expr_or_operand.is_literal:
            if self.arg2_name in Variable.var_table:
                if Variable.var_table[self.arg2_name].datatype != 'int':
                    raise ValueError(f"Variable {self.arg2_name} is not an integer")
                if Variable.var_table[self.arg2_name].addr != 0x00000000:
                    self.arg2 = Variable.var_table[self.arg2_name].addr
                else:
                    resolved = False
        
        self.resolved = resolved
        return self.resolved
    
    def expr_section_size(self):
        return self.arg2_section_size
    
    def expr_section_bytes(self):
        if not self.resolve():
            raise ValueError("Cannot serialize unresolved expression section")
        
        if self.arg2_is_expression:
            expr_bytes = b''
            for cmd in self.expr_or_operand.commands:
                expr_bytes += cmd.to_bytes()
            return expr_bytes
        else:
            return b''
        
    def size(self):
        return self.expr_section_size() + super().size()
    
    def to_bytes(self):
        if not self.resolve():
            raise ValueError("Cannot serialize unresolved expression section")
        
        return self.expr_section_bytes() + super().to_bytes()
    
    def __repr__(self) -> str:
        if not self.resolve():
            return f"{self.command_type.name}: UNRESOLVED"

        return f"{self.expr_or_operand.commands if self.arg2_is_expression else ''} {super().__repr__()}"

class CommandSetInt(CommandWithIntExpressionArgument):
    def __init__(self, instring, loc, dst : str, src : GqcIntOperand | IntExpression = None):
        
        self.dst_name = dst

        super().__init__(CommandType.SETVAR, instring, loc, src)

        self.command_flags |= structs.OpFlags.TYPE_INT
    
    def resolve(self):
        if self.resolved:
            return True

        resolved = True

        # Resolve the expression section, if any:
        if not super().resolve():
            resolved = False
            return False

        # TODO: Test for null differently:
        # TODO: Test for valid memory namespaces:
        if self.dst_name in Variable.var_table and Variable.var_table[self.dst_name].addr != 0x00000000:
            self.arg1 = Variable.var_table[self.dst_name].addr
        else:
            resolved = False
        
        self.resolved = resolved
        
        return self.resolved

class CommandIf(CommandWithIntExpressionArgument):
    def __init__(self, instring, loc, condition : GqcIntOperand | IntExpression, true_cmds : list, false_cmds : list = None):
        super().__init__(CommandType.GOTOIFN, instring, loc, condition)
        self.true_cmds = true_cmds
        self.false_cmds = false_cmds

        self.true_section_size = 0
        for cmd in self.true_cmds:
            self.true_section_size += cmd.size()
        
        self.false_section_size = 0
        if self.false_cmds:
            for cmd in self.false_cmds:
                self.false_section_size += cmd.size()
        
        if self.false_section_size != 0:
            self.true_section_size += structs.GQ_OP_SIZE

        self.resolve()
    
    def resolve(self):
        if self.resolved:
            return True
        
        if not super().resolve():
            return False

        resolved = True

        # TODO: We can probably optimize away any literal conditionals.

        # Resolve the true commands.
        for cmd in self.true_cmds:
            if not cmd.resolve():
                resolved = False
        
        # Resolve the false commands.
        if self.false_cmds:
            for cmd in self.false_cmds:
                if not cmd.resolve():
                    resolved = False

        self.resolved = resolved
        return self.resolved
    
    def size(self):
        # The size of this if block is the size of the GOTOIFN command, plus the size of the true section,
        #  plus the size of the false section.
        return self.expr_section_size() + super().size() + self.true_section_size + self.false_section_size
    
    def to_bytes(self):
        if not self.resolve():
            # This also confirms that the condition is resolved.
            raise ValueError("Cannot serialize unresolved IF block")

        if not self.addr:
            raise ValueError("Cannot serialize IF block without base address set")
        
        # If there's an expression section required, this will serialize it.
        #  Otherwise, it will be an empty byte string.
        cmd_bytes = self.expr_section_bytes()

        # Next, serialize the GOTOIFN command.
        cmd_bytes += super().to_bytes()

        # Next, serialize the true commands.
        for cmd in self.true_cmds:
            cmd_bytes += cmd.to_bytes()
        
        # If there are false commands, we need to add a GOTO command to jump over them,
        #  and then serialize the false commands.
        if self.false_cmds:
            cmd_bytes += CommandGoto(None, None, self.addr + self.size()).to_bytes()
            for cmd in self.false_cmds:
                cmd_bytes += cmd.to_bytes()
        
        return cmd_bytes
    
    def set_addr(self, addr: int, namespace: int = structs.GQ_PTR_NS_CART):
        if not self.resolve():
            raise ValueError("Cannot set address of unresolved IF block")
        
        super().set_addr(addr, namespace)
        false_address = self.addr + super().size() + self.true_section_size
        self.arg1 = false_address


    def __repr__(self) -> str:
        if not self.resolve():
            return f"IF: UNRESOLVED"

        return f"{self.expr_or_operand.commands if self.arg2_is_expression else ''} {super().__repr__()} {self.true_cmds} {(repr(CommandGoto(None, None, self.addr + self.size())) + ' ') if self.false_cmds else ''}{self.false_cmds if self.false_cmds else ''}"

class CommandLoop():
    def __init__(self, instring, loc, commands : list):
        self.instring = instring
        self.loc = loc
        self.commands = commands
        self.addr = 0x00000000
        self.done_addr = 0x00000000
        self.resolved = False

        self.commands.append(CommandGoto(instring, loc, form='continue'))

    def set_addr(self, addr : int, namespace : int = structs.GQ_PTR_NS_CART):
        self.addr = structs.gq_ptr_apply_ns(namespace, addr)
        self.done_addr = self.addr + self.size()
    
    def size(self):
        size = 0
        for cmd in self.commands:
            size += cmd.size()
        return size
    
    def set_goto_addrs(self, commands: list):
        for cmd in commands:
            if isinstance(cmd, CommandGoto):
                if cmd.form == 'continue':
                    cmd.arg1 = self.addr
                elif cmd.form == 'break':
                    cmd.arg1 = self.done_addr
            elif isinstance(cmd, CommandIf):
                self.set_goto_addrs(cmd.true_cmds)
                if cmd.false_cmds:
                    self.set_goto_addrs(cmd.false_cmds)

    def resolve(self):
        if self.resolved:
            return True
        
        resolved = True

        self.set_goto_addrs(self.commands)

        for cmd in self.commands:
            if not cmd.resolve():
                resolved = False
        
        self.resolved = resolved
        return self.resolved
    
class CommandTimer(CommandWithIntExpressionArgument):
    def __init__(self, instring, loc, interval : GqcIntOperand | IntExpression):
        super().__init__(CommandType.TIMER, instring, loc, interval)
    
    # def __repr__(self) -> str:
    #     return f"TIMER {self.arg2}"

class CommandLoop(Command):
    pass
