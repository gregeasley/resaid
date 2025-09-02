"""
Setup configuration for RESAID package.

Build commands:
- For conda: python setup.py bdist_conda && conda install --use-local resaid
- For pip: pip install -e . (development) or pip install . (production)

References:
- https://packaging.python.org/tutorials/packaging-projects/
- https://towardsdatascience.com/how-to-package-your-python-code-df5a7739ab2e
"""

import setuptools


with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setuptools.setup(
    name="resaid",
    version="0.2.2",
    author="Greg Easley",
    author_email="greg@easley.dev",
    license="MIT",
    description="Comprehensive reservoir engineering tools for decline curve analysis and production forecasting",
    long_description=long_description,
    long_description_content_type="text/markdown",
    keywords="reservoir engineering, decline curve analysis, production forecasting, oil and gas, DCA, arps",
    url="https://github.com/gregeasley/resaid",
    project_urls={
        "Bug Tracker": "https://github.com/gregeasley/resaid/issues",
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Science/Research",
        "Topic :: Scientific/Engineering",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    install_requires=[
        'numpy>=1.22',
        'pandas>=1.5.3',
        'scipy>=1.0.0',
        'statsmodels>=0.13.5',
        'python-dateutil>=2.8.0',
        'tqdm>=4.65.0',
    ],
    packages=setuptools.find_packages(),
    python_requires=">=3.8",
    include_package_data=False,
)