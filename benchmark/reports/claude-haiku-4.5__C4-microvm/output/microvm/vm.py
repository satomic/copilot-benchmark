from .compiler import Program
from .errors import VMRuntimeError, StepLimitError


def execute(program: Program, *, step_limit: int = 100_000) -> list[str]:
    if not isinstance(step_limit, int) or step_limit <= 0 or isinstance(step_limit, bool):
        raise ValueError("step_limit must be a positive integer")
    vm = VM(program, step_limit)
    return vm.run()


class VM:
    def __init__(self, program: Program, step_limit: int):
        self.program = program
        self.step_limit = step_limit
        self.pc = 0
        self.stack = []
        self.variables = [None] * len(program.names)
        self.assigned = [False] * len(program.names)
        self.steps = 0
        self.output = []

    def run(self) -> list[str]:
        while self.pc < len(self.program.instructions):
            if self.steps > self.step_limit:
                raise StepLimitError("Step limit exceeded")
            self.steps += 1
            instr = self.program.instructions[self.pc]
            self.execute_instr(instr)
            self.pc += 1
        return self.output

    def execute_instr(self, instr):
        if instr.op == "CONST":
            self.stack.append(self.program.constants[instr.arg])
        elif instr.op == "LOAD":
            if not self.assigned[instr.arg]:
                raise VMRuntimeError(f"Variable '{self.program.names[instr.arg]}' not assigned")
            self.stack.append(self.variables[instr.arg])
        elif instr.op == "STORE":
            val = self.stack.pop()
            self.variables[instr.arg] = val
            self.assigned[instr.arg] = True
        elif instr.op == "ADD":
            right = self.stack.pop()
            left = self.stack.pop()
            if isinstance(left, str) and isinstance(right, str):
                self.stack.append(left + right)
            elif isinstance(left, bool) or isinstance(right, bool):
                raise VMRuntimeError("Cannot add bool")
            elif isinstance(left, (int, float)) and isinstance(right, (int, float)):
                result = left + right
                self.stack.append(result)
            else:
                raise VMRuntimeError("Type error in +")
        elif instr.op == "SUB":
            right = self.stack.pop()
            left = self.stack.pop()
            if isinstance(left, bool) or isinstance(right, bool):
                raise VMRuntimeError("Cannot subtract bool")
            if not (isinstance(left, (int, float)) and isinstance(right, (int, float))):
                raise VMRuntimeError("Type error in -")
            self.stack.append(left - right)
        elif instr.op == "MUL":
            right = self.stack.pop()
            left = self.stack.pop()
            if isinstance(left, bool) or isinstance(right, bool):
                raise VMRuntimeError("Cannot multiply bool")
            if not (isinstance(left, (int, float)) and isinstance(right, (int, float))):
                raise VMRuntimeError("Type error in *")
            self.stack.append(left * right)
        elif instr.op == "DIV":
            right = self.stack.pop()
            left = self.stack.pop()
            if isinstance(left, bool) or isinstance(right, bool):
                raise VMRuntimeError("Cannot divide bool")
            if not (isinstance(left, (int, float)) and isinstance(right, (int, float))):
                raise VMRuntimeError("Type error in /")
            if right == 0:
                raise VMRuntimeError("Division by zero")
            self.stack.append(left / right)
        elif instr.op == "MOD":
            right = self.stack.pop()
            left = self.stack.pop()
            if not (isinstance(left, int) and isinstance(right, int)):
                raise VMRuntimeError("Modulo requires integers")
            if right == 0:
                raise VMRuntimeError("Modulo by zero")
            self.stack.append(left % right)
        elif instr.op == "NEG":
            val = self.stack.pop()
            if isinstance(val, bool):
                raise VMRuntimeError("Cannot negate bool")
            if not isinstance(val, (int, float)):
                raise VMRuntimeError("Cannot negate non-number")
            self.stack.append(-val)
        elif instr.op == "NOT":
            val = self.stack.pop()
            if not isinstance(val, bool):
                raise VMRuntimeError("not requires bool")
            self.stack.append(not val)
        elif instr.op == "EQ":
            right = self.stack.pop()
            left = self.stack.pop()
            if isinstance(left, bool) != isinstance(right, bool):
                self.stack.append(False)
            else:
                self.stack.append(left == right)
        elif instr.op == "NE":
            right = self.stack.pop()
            left = self.stack.pop()
            if isinstance(left, bool) != isinstance(right, bool):
                self.stack.append(True)
            else:
                self.stack.append(left != right)
        elif instr.op == "LT":
            right = self.stack.pop()
            left = self.stack.pop()
            if isinstance(left, bool) or isinstance(right, bool):
                raise VMRuntimeError("Cannot compare bool with <")
            if (isinstance(left, (int, float)) and isinstance(right, (int, float))) or \
               (isinstance(left, str) and isinstance(right, str)):
                self.stack.append(left < right)
            else:
                raise VMRuntimeError("Type error in <")
        elif instr.op == "LE":
            right = self.stack.pop()
            left = self.stack.pop()
            if isinstance(left, bool) or isinstance(right, bool):
                raise VMRuntimeError("Cannot compare bool with <=")
            if (isinstance(left, (int, float)) and isinstance(right, (int, float))) or \
               (isinstance(left, str) and isinstance(right, str)):
                self.stack.append(left <= right)
            else:
                raise VMRuntimeError("Type error in <=")
        elif instr.op == "GT":
            right = self.stack.pop()
            left = self.stack.pop()
            if isinstance(left, bool) or isinstance(right, bool):
                raise VMRuntimeError("Cannot compare bool with >")
            if (isinstance(left, (int, float)) and isinstance(right, (int, float))) or \
               (isinstance(left, str) and isinstance(right, str)):
                self.stack.append(left > right)
            else:
                raise VMRuntimeError("Type error in >")
        elif instr.op == "GE":
            right = self.stack.pop()
            left = self.stack.pop()
            if isinstance(left, bool) or isinstance(right, bool):
                raise VMRuntimeError("Cannot compare bool with >=")
            if (isinstance(left, (int, float)) and isinstance(right, (int, float))) or \
               (isinstance(left, str) and isinstance(right, str)):
                self.stack.append(left >= right)
            else:
                raise VMRuntimeError("Type error in >=")
        elif instr.op == "JUMP":
            self.pc = instr.arg - 1
        elif instr.op == "JUMP_IF_FALSE":
            val = self.stack.pop()
            if not isinstance(val, bool):
                raise VMRuntimeError("Condition must be bool")
            if not val:
                self.pc = instr.arg - 1
        elif instr.op == "PRINT":
            val = self.stack.pop()
            if isinstance(val, bool):
                self.output.append("true" if val else "false")
            else:
                self.output.append(str(val))
        elif instr.op == "POP":
            self.stack.pop()
        elif instr.op == "HALT":
            self.pc = len(self.program.instructions)
