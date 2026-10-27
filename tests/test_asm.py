import unittest

from grider.asm import AssemblyError, assemble, load_kernel
from grider.sim import DataType, Opcode


class AssemblerTests(unittest.TestCase):
    def test_parses_instruction_forms_and_directives(self):
        program = assemble("""
            .dtype i8
            .mask 0x3
            nop
            mov r0, r1
            movi r2, -7
            add r3, r0, r1
            mac r4, r0, r1
            sel r5, r0, r1, r2, i16
            neighbor r6, r5, nw
            load r7, 3
            store r7, 4
            reduce_sum r8, r7
            reduce_max r9, r7, bf16
        """)
        self.assertEqual([instruction.opcode for instruction in program], [
            Opcode.NOP, Opcode.MOV, Opcode.MOVI, Opcode.ADD, Opcode.MAC,
            Opcode.SEL, Opcode.NEIGHBOR, Opcode.LOAD, Opcode.STORE,
            Opcode.REDUCE_SUM, Opcode.REDUCE_MAX,
        ])
        self.assertTrue(all(instruction.lane_mask == 3 for instruction in program))
        self.assertEqual(program[2].imm, -7)
        self.assertEqual(program[5].dtype, DataType.I16)
        self.assertEqual(program[6].imm, 7)
        self.assertEqual(program[-1].dtype, DataType.BF16)

    def test_repeat_expands_expressions_and_nested_variables(self):
        program = assemble("""
            .repeat 2 as row
                .repeat 3 as col
                    movi r0, {row} * 16 + {col}, i32
                .endrepeat
            .endrepeat
        """)
        self.assertEqual([instruction.imm for instruction in program], [0, 1, 2, 16, 17, 18])

    def test_bf16_float_immediate_and_kernel_loading(self):
        program = assemble(".dtype bf16\nmovi r0, 1.5\n")
        self.assertEqual(program[0].dtype, DataType.BF16)
        self.assertEqual(len(load_kernel("vector_add_bf16")), 1)
        self.assertEqual(len(load_kernel("row_sum_i32")), 1)
        self.assertEqual(len(load_kernel("matmul16_bf16")), 65)

    def test_errors_include_source_line_and_reject_unsafe_expressions(self):
        with self.assertRaisesRegex(AssemblyError, r"line 2: unknown instruction"):
            assemble("nop\nnot_an_opcode r0\n")
        with self.assertRaisesRegex(AssemblyError, r"line 1:.*invalid numeric expression"):
            assemble("movi r0, __import__('os')\n")
        with self.assertRaisesRegex(AssemblyError, "unterminated .repeat"):
            assemble(".repeat 2 as i\nnop\n")


if __name__ == "__main__":
    unittest.main()
