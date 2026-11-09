files = [
    "software_gpu/tests/test_performance_edge_covered.py",
    "software_gpu/tests/test_band_inline_parity.py",
    "software_gpu/tests/test_postprocess_clip_parity.py"
]

for file in files:
    with open(file, "r") as f:
        content = f.read()

    # We want to move the appended block inside the class or at least before the __main__ block.
    # The simplest way is to find the "if __name__" block and move it to the end.

    main_block = 'if __name__ == "__main__":\n    unittest.main()'
    main_block2 = "if __name__ == '__main__':\n    unittest.main()"

    if main_block in content:
        content = content.replace(main_block, "")
        content = content.strip() + "\n\n" + main_block + "\n"
    elif main_block2 in content:
        content = content.replace(main_block2, "")
        content = content.strip() + "\n\n" + main_block2 + "\n"

    with open(file, "w") as f:
        f.write(content)
