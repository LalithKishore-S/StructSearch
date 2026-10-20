class Node:
    def __init__(self, value, left=None, right=None):
        self.value = value
        self.left = left
        self.right = right


def inorder_traverse(node, visit):
    """Recursive in-order tree traversal."""
    if node is None:
        return
    inorder_traverse(node.left, visit)
    visit(node.value)
    inorder_traverse(node.right, visit)


def factorial(n):
    """Compute factorial recursively."""
    if n <= 1:
        return 1
    return n * factorial(n - 1)


def count_nodes(root):
    """Count nodes using an explicit stack (iterative, not recursive)."""
    if root is None:
        return 0
    stack = [root]
    total = 0
    while stack:
        current = stack.pop()
        total += 1
        if current.left:
            stack.append(current.left)
        if current.right:
            stack.append(current.right)
    return total
