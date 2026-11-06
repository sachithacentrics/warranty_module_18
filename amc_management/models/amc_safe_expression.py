"""Controlled expression builder of the Hybrid AMC pricing (SRS 2.12: "approved expression
builder rather than unrestricted Python"). The expression is parsed with the Python AST and
evaluated by this module only - never with eval / safe_eval: numbers, the approved variables,
+ - * /, unary minus / plus, parentheses and the functions min, max, round, abs."""
import ast

MAX_LENGTH = 500
FUNCTIONS = {'min': min, 'max': max, 'round': round, 'abs': abs}
OPERATORS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
}


class AmcExpressionError(ValueError):
    """Invalid expression or evaluation error (message for the user)."""


def _parse(expression):
    expression = (expression or '').strip()
    if not expression:
        raise AmcExpressionError("The expression is empty.")
    if len(expression) > MAX_LENGTH:
        raise AmcExpressionError("The expression is longer than %s characters." % MAX_LENGTH)
    try:
        return ast.parse(expression, mode='eval')
    except SyntaxError as error:
        raise AmcExpressionError("Syntax error: %s." % (error.msg,)) from None


def _check(node, variables):
    if isinstance(node, ast.Expression):
        return _check(node.body, variables)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise AmcExpressionError("Only numbers are allowed as constants.")
        return
    if isinstance(node, ast.Name):
        if node.id not in variables:
            raise AmcExpressionError("Unknown variable '%s'. Allowed: %s." % (
                node.id, ', '.join(sorted(variables))))
        return
    if isinstance(node, ast.BinOp):
        if type(node.op) not in OPERATORS:
            raise AmcExpressionError("Only + - * / are allowed.")
        _check(node.left, variables)
        _check(node.right, variables)
        return
    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, (ast.USub, ast.UAdd)):
            raise AmcExpressionError("Only the signs + and - are allowed.")
        _check(node.operand, variables)
        return
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS \
                or node.keywords or not node.args:
            raise AmcExpressionError("Only the functions %s are allowed." % ', '.join(FUNCTIONS))
        for arg in node.args:
            _check(arg, variables)
        return
    raise AmcExpressionError("'%s' is not allowed in a pricing expression." % (
        type(node).__name__,))


def check_expression(expression, variables):
    """Raise AmcExpressionError when the expression is not a controlled pricing expression."""
    _check(_parse(expression), set(variables))


def _evaluate(node, values):
    if isinstance(node, ast.Expression):
        return _evaluate(node.body, values)
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.Name):
        return float(values[node.id])
    if isinstance(node, ast.BinOp):
        left, right = _evaluate(node.left, values), _evaluate(node.right, values)
        if isinstance(node.op, ast.Div) and right == 0:
            raise AmcExpressionError("Division by zero.")
        return OPERATORS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp):
        value = _evaluate(node.operand, values)
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.Call):
        args = [_evaluate(arg, values) for arg in node.args]
        if node.func.id == 'round':
            return float(round(args[0], int(args[1]) if len(args) > 1 else 0))
        if node.func.id == 'abs':
            return abs(args[0])
        return float(FUNCTIONS[node.func.id](args))
    raise AmcExpressionError("'%s' is not allowed in a pricing expression." % (
        type(node).__name__,))


def evaluate_expression(expression, values):
    """Check and evaluate the expression with `values` {variable: number}."""
    tree = _parse(expression)
    _check(tree, set(values))
    return _evaluate(tree, values)
