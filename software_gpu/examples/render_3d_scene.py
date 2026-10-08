"""
Demonstration: Software GPU 3D Graphics Pipeline.
Renders an illuminated 3D scene completely on CPU using SoftwareRasterizer.
Saves rendered frame as uncompressed BMP.
"""

import math
import numpy as np
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.shader import Vertex, BlinnPhongShader, Matrix4
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.core.output import output_file


def generate_sphere(radius: float = 1.0, stacks: int = 16, slices: int = 16):
    """Generates vertices and triangle indices for a 3D UV sphere."""
    vertices = []
    indices = []

    for i in range(stacks + 1):
        phi = math.pi * float(i) / float(stacks)  # from 0 to pi
        y = radius * math.cos(phi)
        r_slice = radius * math.sin(phi)

        for j in range(slices + 1):
            theta = 2.0 * math.pi * float(j) / float(slices)  # from 0 to 2*pi
            x = r_slice * math.sin(theta)
            z = r_slice * math.cos(theta)

            nx, ny, nz = x / radius, y / radius, z / radius
            u = float(j) / float(slices)
            v = float(i) / float(stacks)

            vertices.append(Vertex(
                position=np.array([x, y, z], dtype=np.float32),
                normal=np.array([nx, ny, nz], dtype=np.float32),
                uv=np.array([u, v], dtype=np.float32),
                color=np.array([0.2, 0.7, 1.0], dtype=np.float32)
            ))

    for i in range(stacks):
        for j in range(slices):
            first = i * (slices + 1) + j
            second = first + slices + 1

            indices.append((first, second, first + 1))
            indices.append((second, second + 1, first + 1))

    return vertices, indices


def main():
    print("=== Software GPU 3D Graphics Pipeline Demo ===")
    width, height = 400, 300
    fb = Framebuffer(width, height)
    # Clear background to a gradient or dark slate color
    fb.clear(r=15, g=20, b=30, a=255, depth=1.0)

    print(f"Generating 3D Sphere geometry (stacks=20, slices=20)...")
    verts, indices = generate_sphere(radius=1.2, stacks=20, slices=20)
    print(f"Total vertices: {len(verts)}, Triangles: {len(indices)}")

    # Camera & Scene matrices
    model = Matrix4.rotation_x(np.radians(20.0)) @ Matrix4.rotation_y(np.radians(35.0))
    view = Matrix4.look_at(
        eye=np.array([0.0, 0.5, 3.2], dtype=np.float32),
        target=np.array([0.0, 0.0, 0.0], dtype=np.float32),
        up=np.array([0.0, 1.0, 0.0], dtype=np.float32)
    )
    proj = Matrix4.perspective(
        fov_rad=np.radians(45.0),
        aspect=float(width) / float(height),
        near=0.1,
        far=10.0
    )

    # Blinn-Phong lighting shader
    shader = BlinnPhongShader(
        model_matrix=model,
        view_matrix=view,
        proj_matrix=proj,
        light_dir=np.array([1.0, 2.0, 1.5], dtype=np.float32),
        ambient_color=np.array([0.15, 0.20, 0.30], dtype=np.float32),
        diffuse_color=np.array([0.1, 0.65, 0.95], dtype=np.float32),
        specular_color=np.array([1.0, 1.0, 1.0], dtype=np.float32),
        shininess=48.0
    )

    rasterizer = SoftwareRasterizer(fb)
    print(f"Rasterizing 3D scene using multi-threaded CPU SoftwareRasterizer...")
    rasterizer.draw_mesh(verts, indices, shader)

    output_path = output_file("software_gpu_sphere.bmp")
    fb.save_bmp(output_path)
    print(f"Render completed! Image saved to: {output_path}")


if __name__ == "__main__":
    main()
