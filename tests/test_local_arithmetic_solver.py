from tg_signer.core.local_solver import ArithmeticFastSolver


def test_arithmetic_solver_standard_operations():
    solver = ArithmeticFastSolver()
    assert solver.solve("请计算 15 + 28 = ?") == 43
    assert solver.solve("验证码：100 - 37") == 63
    assert solver.solve("6 * 7") == 42
    assert solver.solve("80 / 4") == 20


def test_arithmetic_solver_rejects_bool_and_div_zero():
    solver = ArithmeticFastSolver()
    # 除零安全返回 None
    assert solver.solve("10 / 0 = ?") is None
    # 严禁 Name/调用/布尔值
    assert solver.solve("True + 1") is None
    assert solver.solve("__import__('os')") is None
    # 幂运算或非法操作返回 None
    assert solver.solve("2 ** 10") is None
