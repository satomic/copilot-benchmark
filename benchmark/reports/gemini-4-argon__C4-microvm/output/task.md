# Task C4: `microvm`, A Bytecode Compiler And Stack Virtual Machine

**Difficulty:** Very complex

## Working agreement (read this first)

- This folder is the project root. Do not read or write anything outside it.
- Python 3.11 and `pytest` are available. Use the **standard library only**. Do not install
  any third-party package and do not access the network.
- Do not use `ast`, `compile()`, `eval`, `exec`, `dis`, `marshal`, `pickle`, or `ctypes`.
  The lexer, parser, compiler, virtual machine and binary codec must be your own code.
  `struct`, `zlib`, `dataclasses`, `argparse`, `re` are all fine.
- Create **exactly** the files listed under *Deliverables*. Do not add extra files
  (no `README.md`, no scratch files). Temporary files written by your own tests must go
  under pytest's `tmp_path`.
- Do not ask clarifying questions. If something is genuinely ambiguous, choose the most
  reasonable interpretation, implement it, and record the choice in a short code comment.
- When the deliverables satisfy the acceptance criteria, stop.

## Goal

Implement a small imperative language end to end: tokenize, parse, compile to bytecode,
optionally constant-fold, execute on a stack VM with a step budget, serialize compiled
programs to a checksummed binary format, disassemble them, and drive it all from a CLI.

The hard parts are (a) **short-circuit logic compiled as jumps without losing the
strict-bool rule**, (b) **constant folding that never changes observable behaviour**, and
(c) **a binary codec that fails loudly on every malformed input**.

## Deliverables

```
microvm/__init__.py        # re-exports, __all__ (exact list in section 10)
microvm/errors.py          # exception hierarchy (section 9)
microvm/opcodes.py         # OPCODES, OPCODE_NUMBERS (section 4)
microvm/lexer.py           # tokenize(), Token (section 2)
microvm/parser.py          # parse() (section 3)
microvm/compiler.py        # compile_source(), Program, Instr (section 4)
microvm/optimizer.py       # fold_constants() (section 6)
microvm/vm.py              # execute() (section 5)
microvm/serializer.py      # dumps(), loads() (section 7)
microvm/disassembler.py    # disassemble() (section 8)
microvm/__main__.py        # CLI (section 11)
tests/test_microvm.py      # your own tests, at least 45 test functions
```

No other files. `tests/` needs no `__init__.py`.

## 1. The language

```
let x = 1 + 2;              // declaration with mandatory initializer
x = x * 3;                  // assignment to a declared name
print x;                    // output
if (x > 5) { print "big"; } else if (x > 2) { print "mid"; } else { print "small"; }
while (x > 0) { x = x - 1; }
```

- Statements: `let`, assignment, `print`, `if` (with optional `else`, where `else` may be
  followed by a block or another `if`), `while`, and a block `{ ... }`.
  `let`, assignment and `print` end with `;`.
- **Keywords are lowercase and the language is case sensitive.** `IF` is an identifier.
  Keywords: `let print if else while true false and or not`. Keywords are never identifiers.
- Values: `INT` (Python `int`), `FLOAT` (`float`), `STRING` (`str`), `BOOL` (`bool`).
  **`bool` is not a number**: any rule below that says "numbers" excludes `bool`, even
  though Python's `isinstance(True, int)` is true.
- **Blocks do not create scope.** There is a single global namespace. `let` anywhere,
  including inside a block, declares the name for the whole program.
- Declaring the same name twice with `let` is a `CompileError`. Assigning to or reading a
  name never declared is a `CompileError`. Both are compile-time.
- A `let` inside a branch that never executes still declares its name at compile time but
  never stores a value. **Reading a declared-but-never-assigned variable raises
  `VMRuntimeError` at run time.**

### Expressions, lowest precedence first

```
expr        := or_expr
or_expr     := and_expr (or and_expr)*
and_expr    := not_expr (and not_expr)*
not_expr    := not not_expr | comparison
comparison  := additive ((== | != | < | <= | > | >=) additive)?
additive    := multiplicative ((+ | -) multiplicative)*
multiplicative := unary ((* | / | %) unary)*
unary       := - unary | primary
primary     := INT | FLOAT | STRING | true | false | IDENT | ( expr )
```

**Comparison is not associative**: `1 < 2 < 3` is a `ParseError`.

### Semantics (all checks happen at run time unless stated otherwise)

1. `+ - *`: numbers only; `INT op INT` yields `INT`, any `FLOAT` operand yields `FLOAT`.
   **Exception: `+` on two `STRING`s concatenates.** `STRING + INT` is a `VMRuntimeError`.
2. **`/` always yields `FLOAT`**, `7 / 2` is `3.5`. `%` requires two `INT`s and follows
   Python's sign rule (`-7 % 3` is `2`).
3. **Division or modulo by zero raises `VMRuntimeError`** (unlike some languages that
   return a null; here it is an error).
4. Unary `-` requires a number.
5. `==` and `!=` never raise: operands of different types are simply not equal, and
   **`BOOL` differs from `INT`** (`true == 1` is `false`) while **`INT` and `FLOAT`
   compare numerically** (`1 == 1.0` is `true`).
6. `< <= > >=`: two numbers (cross-type INT/FLOAT fine), or two `STRING`s by code point.
   `BOOL` operands or any other mixture raise `VMRuntimeError`.
7. `and` / `or` / `not` require `BOOL` operands and **must short-circuit**:
   the right operand of `and` is not evaluated when the left is `false`, and of `or`
   when the left is `true`. `false and (1 / 0 == 0)` is `false`, no error.
   When an operand IS evaluated it must be `BOOL`: `true and 5` raises `VMRuntimeError`.
8. The condition of `if` and `while` must be `BOOL`, else `VMRuntimeError`.
9. `print` renders: `INT` via `str()`, `FLOAT` via `str()` (`4 / 2` prints `2.0`),
   `BOOL` as `true` / `false`, `STRING` as its raw characters, no quotes.

## 2. Lexer: `microvm/lexer.py`

```python
@dataclasses.dataclass(frozen=True)
class Token:
    kind: str      # "INT" | "FLOAT" | "STRING" | "IDENT" | "KEYWORD" | "OP"
    text: str      # the source lexeme (for STRING: the decoded value, see below)
    value: object  # INT -> int, FLOAT -> float, STRING -> decoded str, else same as text
    offset: int    # zero-based character offset of the first character

def tokenize(src: str) -> list[Token]
```

1. Whitespace separates tokens. `//` starts a comment to end of line.
2. Integers are digits. **Floats are `digits.digits`**, optionally with an exponent
   (`1.5e3`, `2.0E-2`). **`1.` and `.5` are a `LexError`** (unlike some languages).
3. Strings are double-quoted; escapes are exactly `\n`, `\t`, `\"`, `\\`; any other escape,
   an unterminated string, or a literal newline inside a string is a `LexError`.
   For a STRING token both `text` and `value` hold the decoded value.
4. Identifiers match `[A-Za-z_][A-Za-z0-9_]*`. Keywords (lowercase only) get kind
   `KEYWORD`; `text` and `value` are the keyword itself.
5. Operators: `+ - * / % ( ) { } ; = == != < <= > >=`. Longest match wins (`==` over `=`).
6. Do **not** emit an end-of-input token. Anything unexpected is a `LexError` carrying the
   zero-based `offset` attribute.

## 3. Parser: `microvm/parser.py`

```python
def parse(src: str) -> object      # the AST root; its shape is yours to choose
```

The AST representation is **not** specified and will not be inspected; only `parse`'s
error behaviour is observable: any malformed program raises `ParseError` with a zero-based
`offset` attribute (`LexError` from tokenization passes through unchanged).

## 4. Bytecode: `microvm/opcodes.py` and `microvm/compiler.py`

```python
# opcodes.py
OPCODES: tuple[str, ...] = (
    "CONST", "LOAD", "STORE", "ADD", "SUB", "MUL", "DIV", "MOD", "NEG", "NOT",
    "EQ", "NE", "LT", "LE", "GT", "GE", "JUMP", "JUMP_IF_FALSE", "PRINT", "POP", "HALT",
)
OPCODE_NUMBERS: dict[str, int] = {name: index + 1 for index, name in enumerate(OPCODES)}
```

Exactly these 21 opcodes, numbered 1 to 21 in this order. `CONST`, `LOAD`, `STORE`,
`JUMP` and `JUMP_IF_FALSE` take an argument; the rest take none. You do not have to use
every opcode (`POP` exists for encodings that need it), but you may not add new ones.

```python
# compiler.py
@dataclasses.dataclass(frozen=True)
class Instr:
    op: str            # one of OPCODES
    arg: int | None    # None exactly when the opcode takes no argument

@dataclasses.dataclass
class Program:
    constants: list        # the constant pool
    names: list[str]       # variable names, slot order = declaration order
    instructions: list     # list[Instr]

def compile_source(src: str, *, optimize: bool = False) -> Program
```

1. `CONST k` pushes `constants[k]`; `LOAD i` / `STORE i` read and write slot `i` of the
   variables; `JUMP a` / `JUMP_IF_FALSE a` set the instruction pointer to the **absolute
   instruction index** `a`. `JUMP_IF_FALSE` pops the condition and requires it to be
   `BOOL` at run time. `PRINT` pops and outputs. `HALT` stops execution.
2. Binary operator opcodes pop right then left, push the result, and enforce the
   section 1 semantics at run time. `NOT` requires `BOOL`; `NEG` requires a number.
3. **The constant pool is deduplicated by type and value**: `1`, `1.0` and `true` are
   three distinct constants; two occurrences of `1` share one pool entry.
4. **The instruction list ends with exactly one `HALT`**, and `HALT` appears nowhere else.
5. `print <literal>;` compiles to exactly `CONST k` then `PRINT` (plus the final `HALT`),
   so `compile_source("print 1;")` has exactly 3 instructions.
6. Short-circuit `and` / `or` must be compiled with jumps; the encoding is otherwise yours.

## 5. VM: `microvm/vm.py`

```python
def execute(program: Program, *, step_limit: int = 100_000) -> list[str]
```

1. Returns the printed lines in order (`print` renders per section 1 rule 9).
2. Every executed instruction costs one step. When the count **exceeds** `step_limit`,
   raise `StepLimitError` (a subclass of `VMRuntimeError`). `while (true) {}` must
   terminate with `StepLimitError`, never hang.
3. `step_limit` must be a positive `int` (`bool` rejected), else `ValueError`.
4. Reading a declared-but-never-assigned slot raises `VMRuntimeError` naming the variable.
5. All type errors of section 1 are `VMRuntimeError`s raised when the instruction executes.

## 6. Optimizer: `microvm/optimizer.py`

```python
def fold_constants(node: object) -> object    # AST in, AST out
```

`compile_source(..., optimize=True)` folds constants on the AST before code generation.
Folding must **never change observable behaviour**:

1. Fold arithmetic, comparison, unary and `not` over literal operands **only when the
   operation would succeed** under section 1's runtime rules. `1 / 0` stays unfolded and
   still raises `VMRuntimeError` at run time; `"a" + 1` stays unfolded.
2. `and` / `or`: fold when **both** operands are literal `BOOL`s. Also allowed:
   `false and X` folds to `false` and `true or X` folds to `true` for any `X`, because `X`
   would never have been evaluated anyway. **`true and X` / `false or X` must NOT fold to
   `X`**: the original checks at run time that `X` is `BOOL`, and dropping that check
   changes behaviour (`let y = true and 5;` must still raise `VMRuntimeError` when
   optimized).
3. Folding is recursive bottom-up, so `print 1 + 2 * 3;` with `optimize=True` compiles to
   exactly 3 instructions (`CONST 0`, `PRINT`, `HALT`); without `optimize` it has more.
4. `fold_constants` is exposed for testing but the observable contract is via
   `compile_source(optimize=True)`.

## 7. Binary format: `microvm/serializer.py`

```python
def dumps(program: Program) -> bytes
def loads(data: bytes) -> Program
```

All integers **big-endian unsigned** unless stated. Layout:

| part | encoding |
|---|---|
| magic | exactly `b"MVM1"` |
| version | u8, exactly `1` |
| name count | u16, then each name: u16 UTF-8 byte length + bytes |
| constant count | u16, then each constant: tag u8 + payload |
| instruction count | u32, then each instruction: opcode u8 + arg u32 |
| checksum | u32, CRC32 (`zlib.crc32`) of **everything between the magic and the checksum** |

Constant tags: `0x01` INT as **signed** big-endian i64; `0x02` FLOAT as IEEE-754 f64;
`0x03` STRING as u32 UTF-8 byte length + bytes; `0x04` BOOL as u8 `0`/`1`.

1. An `INT` constant outside the signed 64-bit range makes `dumps` raise
   `SerializationError`.
2. Instructions without an argument encode `arg` as `0xFFFFFFFF`; `loads` turns that back
   into `None`. An argument-taking opcode with `0xFFFFFFFF`, or a no-argument opcode with
   anything else, is a `SerializationError`.
3. `loads` raises `SerializationError` for: bad magic, unsupported version, unknown
   constant tag, unknown opcode number, a BOOL payload other than 0 or 1, any truncation,
   trailing bytes after the checksum, and a checksum mismatch. **Validate the checksum
   before trusting any length field.**
4. `dumps` is deterministic: the same `Program` serializes to identical bytes.
5. `execute(loads(dumps(p)))` behaves identically to `execute(p)`.

## 8. Disassembler: `microvm/disassembler.py`

```python
def disassemble(program: Program) -> str
```

One line per instruction, each ending with `\n`:

- no argument: `{index:04d} {OP}`
- with argument: `{index:04d} {OP} {arg}`
- `CONST` additionally appends two spaces, `;`, one space, and the constant rendered as:
  `INT`/`FLOAT` via `str()`, `BOOL` as `true`/`false`, `STRING` in double quotes with
  `\n`, `\t`, `"` and `\` escaped.

`disassemble(compile_source("print 1;"))` is exactly:

```
0000 CONST 0  ; 1
0001 PRINT
0002 HALT
```

## 9. Errors: `microvm/errors.py`

```
MicroVMError(Exception)
├── LexError(MicroVMError)            # .offset (zero-based int)
├── ParseError(MicroVMError)          # .offset (zero-based int)
├── CompileError(MicroVMError)
├── SerializationError(MicroVMError)
└── VMRuntimeError(MicroVMError)
    └── StepLimitError(VMRuntimeError)
```

## 10. `microvm/__init__.py`

`__all__` is exactly these 19 names, all importable from the package root:

```
tokenize, Token, parse, compile_source, Program, Instr, fold_constants, execute,
dumps, loads, disassemble, OPCODES, OPCODE_NUMBERS,
MicroVMError, LexError, ParseError, CompileError, SerializationError, VMRuntimeError
```

(`StepLimitError` lives in `microvm.errors`; re-exporting it is optional and it is **not**
in `__all__`.)

## 11. CLI: `microvm/__main__.py`

`python -m microvm COMMAND ...`, implemented with `argparse` subcommands:

| command | behaviour |
|---|---|
| `run FILE [--optimize] [--step-limit N]` | compile the source file and execute; print each output line to stdout |
| `build FILE OUT [--optimize]` | compile and write `dumps()` bytes to OUT |
| `exec FILE [--step-limit N]` | `loads()` the binary file and execute; print output |
| `disasm FILE` | `loads()` the binary file and print `disassemble()` to stdout |

1. Exit codes: `0` success; `2` usage error (unknown command, missing argument, unreadable
   file, `--step-limit` not a positive integer); `3` any `MicroVMError`, message on stderr.
2. **Nothing is written to stdout on a failure path**, including a `VMRuntimeError` raised
   midway: output is buffered and printed only on success.
3. `main(argv: list[str] | None = None) -> int` returns the exit code and
   `python -m microvm` passes it to `sys.exit`.

## 12. Your own tests

`tests/test_microvm.py`, at least **45** test functions, runnable with
`python -m pytest -q`. Cover at minimum: every section 1 semantic rule, short-circuit
without evaluating the right side, the never-assigned-variable error, constant-pool
dedup including `1` vs `1.0` vs `true`, fold-safety (`1 / 0` and `true and 5` under
`optimize=True`), serializer round trip plus at least three corruption cases, the exact
disassembly of section 8, step limits, and the CLI exit codes. Use `tmp_path`.

## Acceptance criteria

1. `python -m pytest -q` passes from this folder.
2. `python -c "import microvm; print(len(microvm.__all__))"` prints `19`.
3. This prints `5` then `4.0`:
   ```
   echo let x = 5; print x; print 8 / 2; > t.mv
   python -m microvm run t.mv
   ```
4. Every public function and method has type annotations on parameters and return value.
5. **No function body is longer than 60 lines.**
