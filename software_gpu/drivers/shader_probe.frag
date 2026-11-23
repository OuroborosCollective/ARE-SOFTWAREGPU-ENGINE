#version 450
layout(location = 0) in vec3 colorIn;
layout(location = 0) out vec4 finalColor;
void main() {
    finalColor = vec4(colorIn, 1.0);
}
