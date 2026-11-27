import unicodedata

from tg_signer.core.local_solver import (
    _CANDIDATE_REGEX,
    ArithmeticFastSolver,
    normalize_math,
)


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


def test_normalize_math_folds_nfkc_and_maps_unicode_symbols():
    solver = ArithmeticFastSolver()
    # NFKC 折不掉 U+2212，第二步显式映射不能省
    assert "−" in unicodedata.normalize("NFKC", "1 − 1 = ?")
    assert normalize_math("1 − 1 = ?") == "1 - 1 = ?"
    assert normalize_math("3 ➖ 1 = ?") == "3 - 1 = ?"
    assert normalize_math("8 ⁄ 2 = ?") == "8 / 2 = ?"
    assert normalize_math("8 ∕ 2 = ?") == "8 / 2 = ?"
    # 归一化后能解出正确结果
    assert solver.solve("1 − 1 = ?") == 0
    assert solver.solve("3 ➖ 1 = ?") == 2
    assert solver.solve("8 ⁄ 2 = ?") == 4
    assert solver.solve("8 ∕ 2 = ?") == 4


def test_unicode_minus_needs_normalization_to_be_solvable():
    # 证明用例确实覆盖到归一化：未归一化时正则匹配不到，归一化后才可解析
    assert _CANDIDATE_REGEX.search("1 − 1 = ?") is None
    assert _CANDIDATE_REGEX.search("3 ➖ 1 = ?") is None
    assert _CANDIDATE_REGEX.search(normalize_math("1 − 1 = ?")) is not None
    assert _CANDIDATE_REGEX.search(normalize_math("3 ➖ 1 = ?")) is not None
