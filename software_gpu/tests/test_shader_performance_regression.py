import unittest
import ast
from pathlib import Path

class TestShaderPerformanceRegression(unittest.TestCase):
    def test_no_np_dot_in_blinn_phong_fragment_shader(self):
        """
        Ensures that np.dot is not used in the BlinnPhongShader.fragment_shader
        to prevent performance regressions. Explicit scalar math is ~1.7x faster
        due to removing NumPy dynamic dispatch overhead on small fixed-size vectors.
        """
        shader_file_path = Path(__file__).parent.parent / "graphics" / "shader.py"
        with open(shader_file_path, "r", encoding="utf-8") as f:
            source = f.read()

        tree = ast.parse(source)

        class ShaderVisitor(ast.NodeVisitor):
            def __init__(self):
                self.in_blinn_phong = False
                self.in_fragment_shader = False
                self.np_dot_calls = []

            def visit_ClassDef(self, node):
                if node.name == "BlinnPhongShader":
                    self.in_blinn_phong = True
                    self.generic_visit(node)
                    self.in_blinn_phong = False
                else:
                    self.generic_visit(node)

            def visit_FunctionDef(self, node):
                if self.in_blinn_phong and node.name == "fragment_shader":
                    self.in_fragment_shader = True
                    self.generic_visit(node)
                    self.in_fragment_shader = False
                else:
                    self.generic_visit(node)

            def visit_Call(self, node):
                if self.in_fragment_shader:
                    # Check for np.dot call
                    if isinstance(node.func, ast.Attribute):
                        if isinstance(node.func.value, ast.Name) and node.func.value.id == "np" and node.func.attr == "dot":
                            self.np_dot_calls.append(node)
                self.generic_visit(node)

        visitor = ShaderVisitor()
        visitor.visit(tree)

        self.assertEqual(len(visitor.np_dot_calls), 0, "Found np.dot usage in BlinnPhongShader.fragment_shader. Please use explicit scalar math for performance.")

if __name__ == "__main__":
    unittest.main()
