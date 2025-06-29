# test_ujump2_opcode.py

import pytest
from eth import constants
from eth.abc import ComputationAPI
from eth.exceptions import (
    Halt,
    InvalidInstruction,
    InvalidJumpDestination,
)
from eth.tools._utils.pytest import (
    BaseTestCase,
    enable_pytest_assert_rewrite,
)
from eth.vm import opcode_values
from eth.vm.code import Code
from eth.vm.message import Message

# 启用pytest断言重写
enable_pytest_assert_rewrite()

# 测试字节码模板
UJUMP2_VALID_CODE = bytes([
    # 跳转到地址 0x0005 (5字节偏移)
    opcode_values.UJUMP2, 0x00, 0x05,
    0x00, 0x00,  # 填充字节
    opcode_values.JUMPDEST,  # 目标位置 (0x05)
    opcode_values.STOP
])

UJUMP2_INVALID_DEST_CODE = bytes([
    opcode_values.UJUMP2, 0x00, 0x03,  # 跳转到非JUMPDEST位置
    opcode_values.ADD,
    opcode_values.STOP  # 目标位置 (0x03)
])

UJUMP2_OUT_OF_BOUNDS_CODE = bytes([
    opcode_values.UJUMP2, 0xFF, 0xFF  # 跳转到不存在的地址
])

class TestUJump2Opcode(BaseTestCase):
    # 使用Cancun分叉配置
    vm_config = (
        ("vm.configure_support_dao_fork", False),
        ("vm.configure_cancun_fork", True),
    )

    def _execute_code(self, code: bytes) -> ComputationAPI:
        """
        执行自定义字节码的辅助函数
        """
        return self.execute_code(
            code=Code(code),
            message=Message(
                to=constants.CREATE_CONTRACT_ADDRESS,
                sender=constants.ZERO_ADDRESS,
                create_address=constants.ZERO_ADDRESS,
                value=0,
                data=b"",
                code=code,
                gas=1000000,
            )
        )

    def test_valid_ujump2(self):
        """
        测试有效跳转至JUMPDEST位置
        """
        computation = self._execute_code(UJUMP2_VALID_CODE)
        
        # 验证执行成功
        assert computation.is_success
        
        # 验证PC最终停留在STOP操作码位置
        assert computation.code.program_counter == 6  # 0x05 + 1 (JUMPDEST执行后PC+1)
        
        # 验证堆栈为空（未发生意外操作）
        assert len(computation._stack) == 0

    def test_invalid_jump_destination(self):
        """
        测试跳转至非JUMPDEST位置
        """
        with pytest.raises(InvalidJumpDestination) as excinfo:
            self._execute_code(UJUMP2_INVALID_DEST_CODE)
        
        # 验证错误信息
        assert "Invalid Jump Destination" in str(excinfo.value)
        
        # 验证错误位置
        assert excinfo.value.pc == 0  # UJUMP2指令位置

    def test_out_of_bounds_jump(self):
        """
        测试跳转超出代码范围
        """
        with pytest.raises(Halt) as excinfo:
            self._execute_code(UJUMP2_OUT_OF_BOUNDS_CODE)
        
        # 验证错误类型（实际可能抛出不同异常，需根据实现调整）
        assert "Program counter out of bounds" in str(excinfo.value)
        
        # 验证消耗了所有Gas（根据实际Gas规则调整）
        assert excinfo.value.gas_remaining < 1000000

    def test_jump_to_invalid_opcode(self):
        """
        测试跳转至无效操作码位置
        """
        # 构造跳转到无效操作码的字节码
        code = bytes([
            opcode_values.UJUMP2, 0x00, 0x03,
            0x00, 0x00,  # 填充
            0xFE  # 无效操作码 (0x03位置)
        ])
        
        with pytest.raises(InvalidInstruction) as excinfo:
            self._execute_code(code)
        
        # 验证错误位置
        assert excinfo.value.pc == 3  # 跳转后的位置

    def test_jump_forward_execution_flow(self):
        """
        测试跳转后的继续执行
        """
        code = bytes([
            opcode_values.UJUMP2, 0x00, 0x06,  # 跳转到0x06
            0x00, 0x00, 0x00,  # 填充
            opcode_values.JUMPDEST,  # 0x05
            opcode_values.PUSH1, 0x42,  # 0x06-0x07
            opcode_values.STOP        # 0x08
        ])
        
        computation = self._execute_code(code)
        
        # 验证执行成功
        assert computation.is_success
        
        # 验证堆栈中存在压入的0x42
        assert computation.stack_pop() == 0x42

if __name__ == "__main__":
    pytest.main([__file__])