from setuptools import setup

setup(
    name="precharge-calculator",
    version="1.0.0",
    description="RCS Precharge Calculator for WFI",
    author="Maxime Rizzo",
    py_modules=["precharge_calculator"],
    install_requires=[
        "numpy",
        "pandas",
        "openpyxl",
    ],
    entry_points={
        "console_scripts": [
            "precharge-calculator=precharge_calculator:main",
        ],
    },
    python_requires=">=3.8",
)
